import re

from django.http import QueryDict

from dcim.api.views import DeviceViewSet
from dcim.choices import InterfaceTypeChoices
from dcim.models import Device, Interface
from extras.scripts import Script, StringVar


# TODO: See if this NAPALM call through Netbox can be improved upon without handling NAPALM ourselves
# or calling the Netbox API via HTTP
def napalm_call(method: str, device_id: int, request):
    """Function to make NAPALM calls to devices through Netbox internal code

    Args:
        method (str): the NAPALM method to call (only supports 'get' methods due to Netbox limitation)
        device_id (int): the id of the device to execute the NAPALM method on
        request: a :obj:`django.http.HttpRequest` or a :obj:`utilities.utils.NetboxFakeRequest` obtained from a script's run method

    Returns:
        dict: Returns a dict with the results returned by NAPALM
    """
    deviceviewset = DeviceViewSet()
    # Only filter out current device, so we don't prefetch entire database
    deviceviewset.queryset = Device.objects.filter(id=device_id).prefetch_related(
        "platform",
        "primary_ip4__nat_outside",
        "primary_ip6__nat_outside",
    )

    request.headers = []
    request.GET = QueryDict(f"method={method}")
    response = deviceviewset.napalm(request, device_id)
    return response.data[method]


class InterfaceUpdate(Script):
    """Script that can be used to auto generate interfaces from devices using NAPALM

    Args:
        Script (:obj:`extras.script.Script`): Netbox Script object that is needed for a class to be recognized as one
    """

    class Meta:
        """Special class that is used for defining script information"""

        name = "Interface update"
        description = "Script that updates interfaces for device names provided"
        commit_default = False

    device_name = StringVar(
        label="Devices regex",
        default="(r6|v22)-leaf((1\d*|[2-9])|1)",
        description="Regex that will be used to select devices to update interfaces",
    )
    ignore_interfaces = StringVar(
        label="Interfaces to ignore regex",
        default="Vlan.*",
        description="Regex that will ignore interfaces matching it (Leave blank to not ignore any)",
    )

    def run(self, data, commit: bool):
        """The main method of the script that will be run when pressing the Run Script button

        1. Grabs the data from Netbox about devices containing the devices by regex input by the user
        2. Loops through the devices, grabs their current Netbox interfaces and then makes a NAPALM call to the device
        3. Loops through NAPALM interfaces, while ignoring the ones matching the user supplied regex
        4. If a mac_address is any kind of empty or null, it makes sure to set it to python None
        5. Using get_or_create, grabs or creates the interface from Netbox while filtering by the specific NAPALM interface the loop is currently on
        6. Notifies user if a interface was created and if it wasn't checks if the description in Netbox matches NAPALM description
        7. Updates description if neccessary, notifying user of it.

        Args:
            data (dict): a dict that has the variables for user input. Defined using class variables
            commit (bool): a bool that determines to commit or not to commit the changes to database
                        (since Netbox automatically reverts database changes on commit = False, we don't use it)

        Returns:
            str: output for the Output tab
        """
        output = ""
        devices = Device.objects.filter(name__regex=data["device_name"])

        for device in devices:
            netbox_interfaces = Interface.objects.filter(device=device.id)
            napalm_interfaces = napalm_call("get_interfaces", device.id, self.request)

            for napalm_interface in napalm_interfaces:
                # Blacklist interfaces
                if data["ignore_interfaces"] != "" and re.match(
                    data["ignore_interfaces"], napalm_interface
                ):
                    continue

                napalm_description = napalm_interfaces[napalm_interface]["description"]

                mac_address = napalm_interfaces[napalm_interface]["mac_address"]
                if (
                    mac_address == "None"
                    and mac_address == "Unspecified"
                    and mac_address == ""
                ):
                    mac_address = None

                # We don't use update_or_create so we can inform the user when something actually updates
                # update_or_create will update even if nothing changes
                (netbox_interface, created) = netbox_interfaces.get_or_create(
                    name=napalm_interface,
                    defaults={
                        "type": InterfaceTypeChoices.TYPE_OTHER,
                        "description": napalm_description,
                        "device": device,
                        "mac_address": mac_address,
                    },
                )
                if created:
                    self.log_success(
                        f"`[{device.name}]` Created a new interface **({netbox_interface.name})**"
                    )
                else:
                    if netbox_interface.description != napalm_description:
                        old_description = netbox_interface.description
                        netbox_interface.description = napalm_description
                        netbox_interface.save()
                        self.log_success(
                            f"`[{device.name}]` Updated an interface's description **({netbox_interface.name})**: '{old_description}' -> '{napalm_description}'"
                        )

        return output
