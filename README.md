# Netbox custom scripts
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A repository of [Netbox custom scripts](https://netbox.readthedocs.io/en/stable/additional-features/custom-scripts/) that are used in automating Netbox tasks

I am releasing this because I could not find any decent Netbox custom scripts examples except for the guides ones and maybe this will be useful to others.

## Scripts (see [Notes](#notes) for more info):
* Device interface creation/updating using NAPALM library (`interface_update.py`). Requires `extras.run_script` and `dcim.napalm_read` permissions
* Creating/Updating cables between interfaces (`cable_update.py`). Requires `extras.run_script` and `dcim.napalm_read` permissions

## Usage:
* The scripts can be run from the web under Other -> Scripts
* Invoked using a POST request to Netbox API. See [this](https://netbox.readthedocs.io/en/stable/additional-features/custom-scripts/#via-the-api) for an example

## Compatibility (versions/devices that have been tested and known to work)
* Netbox v2.10.5 (lower/newer versions might also work but suggest testing it beforehand)
* Physical and virtual Arista switches (due to use of NAPALM this should work with any NAPALM compatible vendor's switch)

## Setting up a dev environment
1. (Skip to step 4, if you don't have the need for virtual switches) Install and setup [Virtualbox](https://www.virtualbox.org/)
2. Follow [this guide](https://eos.arista.com/sso-login/?redirect_to=/building-a-virtual-lab-with-arista-veos-and-virtualbox/) to setup a 3 vEOS switch and 1 host network within Virtualbox
3. Configure the switches to have a password (go into `enable` and do `username admin privilege 15 secret arista`) and [enable eAPI](https://eos.arista.com/arista-eapi-101/) on the switches
4. Install Netbox using docker on host-1 using [this guide](https://github.com/netbox-community/netbox-docker#quickstart) and configure the `NAPALM_USERNAME` and `NAPALM_PASSWORD` environment variables with the username and password you set in Step 3 or the credentials you are currently accessing your switches
5. (Skip to step 5 if you are not using virtualbox) To be able to connect to Netbox you need to setup port forwarding for host-1 on the NAT interface
6. Add the switches to Netbox
    1. Add a new site (Organization -> Sites)
    2. Add a new manufacturer (Devices -> Manufacturers)
    3. Add a new device type (Devices -> Device Types)
    4. Add a new platform (Devices -> Platforms), make sure you add NAPALM driver for the platform (in this case it would be `eos`)
    5. Add a new device role (Devices -> Device Roles)
    6. Add the device (Devices -> Devices)
    7. Add the management interface to the device (Add components -> Intefaces), make sure it is marked as management interface.
    8. Add a new management IP address (IPAM -> IP addresses) and make sure you set it as the device's primary IP
7. Clone this repository onto host-1
8. (If you are not going to be making changes straight on the VM, skip to Step 10) Make a new virtualenv `python -m venv venv`
9. Install dependencies to help syntax highlighting, formatting and autocomplete. `pip install -r requirementst.txt`. If it fails try to upgrading pip (`pip install --upgrade pip`)
10. Copy everything in the cloned `scripts/` directory to where you docker installation's `scripts/` folder is
11. (If you are not going to be making changes straight on the VM, skip to next step) Hardlink (symlink might not work due to docker) the docker `scripts/` directory to the cloned `scripts/` directory.
12. You can test if the NAPALM integration works by going to a device's configuration and looking at NAPALM tabs (Status, LLDP, Config)
13. If NAPALM is working, you can run the scripts from Other -> Scripts

## Setting up prod environment (this assumes your Netbox is not installed using docker)
### Requirements:
* Python >= 3.6.8 with pip upgraded (preferably >= 21.0.1) and venv installed
* (optional) NAPALM functionality in Netbox needs to be enabled (this readme will go over it but it is preferable to already have it)
* (FW) Able to access the device APIs (ex. Arista eAPI) using a single specific NAPALM user
* (optional) (FW) Able to clone this git repository
* (optional) (FW) Access to `pip install` packages from web
* Netbox environment with the devices/IPs configured
    * Devices need to have the correct device platform assigned
    * Device platforms need to have a NAPALM driver assigned to them based on [this](https://napalm.readthedocs.io/en/latest/support/#general-support-matrix)
    * Devices on either side of a cable needs to have LLDP enabled otherwise a manually added cable will get deleted
    * Make sure the devices a primary IP assigned, otherwise a connection to that device cannot be made. This can be done by attaching an IP to the device's interface and setting that IP as primary in the IP configuration page.
### Setup:
1. Download the repo source code
2. Copy the contents of the `scripts/` folder to your `SCRIPTS_ROOT` defined directory (by default it will most likely be in `/opt/netbox/netbox/scripts`) (`cp netbox_automation-master-scripts/scripts/*.py /opt/netbox/netbox/scripts/`)
3. (Skip to step 4 if you have NAPALM installed) Install NAPALM
    * With the ability to install packages from web
        1. Add Napalm to local requirements for Netbox `echo "napalm" >> /opt/netbox/local_requirements.txt`
        2. Run Netbox's upgrade tool `cd /opt/netbox && ./upgrade.sh`
    * Without the ability to install packages from web
        1. Add Napalm to local requirements for Netbox `echo "napalm" >> /opt/netbox/local_requirements.txt` for future upgrades
        2. On a device that has access to `pip install` (Recommend having a device with python 3.6.8 and pip 21.0.1 installed)
        3. `mkdir deps && cd deps && && pip download pip && pip download napalm`
        4. `tar -cvzf deps.tar.gz ../deps`
        5. Copy it over to the server `scp deps.tar.gz user@host:/home/user`
        6. Extract it on the server `tar -xvzf deps.tar.gz`
        7. Enter the Netbox's virtualenv `source /opt/netbox/venv/bin/activate` (you may need to be `root` if netbox was installed as `root`)
        8. `pip install pip --no-index --find-links deps/ && pip install napalm --no-index --find-links deps/`
4. Configure NAPALM credentials in `/opt/netbox/netbox/netbox/configuration.py`
    * `NAPALM_USERNAME` - user that will be able to access the network devices read-only
    * `NAPALM_PASSWORD` - password of the user that will access the network devices
5. The scripts will now show up under Others -> Scripts. The NAPALM integration can be tested by selecting one of the tabs (Status, LLDP, Config) in device configuration

## Notes
* inteface_update.py
    * This will override the user made descriptions with descriptions on the actual device
    * The interface names are case-sensitive and need to be the same name as defined in device. So having `management1` already defined will make this generate a new `Management1` interface.
* cable_update.py
    * Netbox only supports 1 to 1 cables
    * If a cable is changed, this will delete a cable before adding a new one (limitation of Netbox) so all data on previous cable will be lost