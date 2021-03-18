import re
from typing import List

from django.http import QueryDict
from django.contrib.contenttypes.models import ContentType

from dcim.api.views import DeviceViewSet
from dcim.models import Device, Interface, Cable
from extras.scripts import Script, StringVar, BooleanVar


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


class CableUpdate(Script):
    """Script that can be used to auto generate interfaces from devices using NAPALM

    Args:
        Script (:obj:`extras.script.Script`): Netbox Script object that is needed for a class to be recognized as one
    """

    class Meta:
        """Special class that is used for defining script information"""

        name = "Cable update"
        description = "Script that updates cable connections between network interfaces"
        commit_default = False

    device_name = StringVar(
        label="Devices regex",
        default="(r6|v22)-leaf((1\d*|[2-9])|1)",
        description="Regex that will be used to select devices that will have their interfaces cabled",
        required=True,
    )

    non_existent = BooleanVar(
        label="Non-existent devices",
        default=False,
        description="If the warnings about non-existent devices/interfaces will be shown",
    )

    def run(self, data, commit: bool):
        """The main method of the script that will be run when pressing the Run Script button

        1. Grabs the data from Netbox about devices containing the devices by regex input by the user
        2. Loops through the devices, and makes a NAPALM `get_lldp_neighbors` call to gather local and their remote interfaces
        3. Loops through all LLDP provided local interfaces.
        4. If a mac_address is any kind of empty or null, it makes sure to set it to python None
        5. Makes sure the local interface can be found in Netbox
        6. If a cable is found, it moves to the next iteration and if the remote interface is correct, goes to next iteration
        7. If a cable is found but the remote interface is not the same, makes sure to mark the cable for deletion (Netbox only allows 1 to 1 cable connections)
        8. Makes sure the remote device and interface can be found in Netbox
        9. Deletes the cable if one was found
        10. Creates a new cable using the local and remote interface pair
        11. Calls function to remove cables no longer found in LLDP

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
            napalm_lldp_neighbors = napalm_call(
                "get_lldp_neighbors", device.id, self.request
            )

            lldp_interface_names = []
            for local_interface_name, remote_interface in napalm_lldp_neighbors.items():
                remote_device_name = remote_interface[0]["hostname"]
                remote_interface_name = remote_interface[0]["port"]

                lldp_interface_names.append(local_interface_name)
                try:
                    netbox_local_interface = Interface.objects.get(
                        device=device.id, name=local_interface_name
                    )
                except Interface.DoesNotExist:
                    if data["non_existent"]:
                        self.log_warning(
                            f"""`[{device.name}]` Local interface **({local_interface_name})** for device **({device.name})** could not be found in Netbox.  
                            Please run the interface update script to have all the interfaces for a device generated"""
                        )
                    continue

                delete_cable = False
                if netbox_local_interface.cable is not None:
                    if (
                        netbox_local_interface._cable_peer.name == remote_interface_name
                        and netbox_local_interface._cable_peer.device.name
                        == remote_device_name
                    ):
                        # Cable already exists so we continue on
                        continue
                    else:  # A Netbox cable is connected but not to the interface the device is reporting
                        delete_cable = True  # Don't delete the cable immediately as the remote interface might not be there

                try:
                    remote_device = Device.objects.get(name=remote_device_name)
                    netbox_remote_interface = Interface.objects.get(
                        device=remote_device.id, name=remote_interface_name
                    )
                except Device.DoesNotExist:
                    if data["non_existent"]:
                        self.log_info(
                            f"""`[{device.name}]` Remote device **({remote_device_name})** could not be found in Netbox  
                            Create the device in Netbox and add the **({remote_interface_name})** interface for a cable to be connected"""
                        )
                    continue
                except Interface.DoesNotExist:
                    if data["non_existent"]:
                        self.log_info(
                            f"""`[{device.name}]` Remote Interface **({remote_interface_name})** for device **({remote_device_name})** could not be found in Netbox  
                            Create the interface in Netbox for a cable to be connected"""
                        )
                    continue

                if delete_cable:
                    # Delete a cable that doesn't exist
                    netbox_local_interface.cable.delete()
                    self.log_success(
                        f"`[{device.name}]` Deleting a no longer existing cable: "
                        f"**{netbox_local_interface.name}** "
                        f"({netbox_local_interface.device.name})"
                        " <-> "
                        f"**{netbox_local_interface._cable_peer.name}** "
                        f"({netbox_local_interface._cable_peer.device.name})"
                    )

                # Create a new cable
                dcim_interface_type = ContentType.objects.get(
                    app_label="dcim", model="interface"
                )
                new_cable = Cable(
                    termination_a_type=dcim_interface_type,
                    termination_a_id=netbox_local_interface.id,
                    termination_b_type=dcim_interface_type,
                    termination_b_id=netbox_remote_interface.id,
                )
                new_cable.save()

                self.log_success(
                    f"`[{device.name}]` Creating a new cable: "
                    f"**{netbox_local_interface.name}** "
                    f"({netbox_local_interface.device.name})"
                    " <-> "
                    f"**{netbox_remote_interface.name}** "
                    f"({netbox_remote_interface.device.name})"
                )
            self.remove_old_cables(device, lldp_interface_names)

        return output

    def remove_old_cables(self, device, lldp_interface_names: List[str]):
        """Task that will remove cables that are no longer connected based on LLDP data

        1. Grabs all the interfaces from the specific device, if it has a Netbox cable attached
            and if it wasn't one of the local interfaces returned from LLDP
        2. Loops through them and deletes them

        Args:
            device (:obj:`dcim.models.Device`):
                A Netbox device model of the device that will be checked for old cables
            lldp_interface_names (:obj:`List[str]`):
                A List of local intefaces that have a cable attached from LLDP
        """
        old_cable_interfaces = Interface.objects.filter(
            device=device.id, cable__isnull=False
        ).exclude(name__in=lldp_interface_names)

        for oc_interface in old_cable_interfaces:
            try:
                old_cable = oc_interface.cable
            except:
                # The cable could have already been deleted if it was plugged in the same device
                continue

            old_cable.delete()
            self.log_success(
                f"`[{device.name}]` Deleting an old cable: "
                f"**{old_cable.termination_a.name}** "
                f"({old_cable.termination_a.device.name})"
                " <-> "
                f"**{old_cable.termination_b.name}** "
                f"({old_cable.termination_b.device.name})"
            )
