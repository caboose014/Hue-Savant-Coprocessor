## Philips Hue Savant CoProcessor ##


Welcome to the Philips Hue/Savant CoProcessor. This server is designed to sit in-between Philips Hue and Savant to relay messages and feedback nicely between the two systems.

The reason for this CoProcessor is mainly to poll Philips Hue for updates and push these over to Savant. This removes the need for Savant to continuously poll Philips Hue for updates. The CoProcessor also formats the feedback from Philips Hue into a nice, and easy to work with format for Savant. This allows us to capture all light, group, scene, and sensor information from the Philips Hue Bridge.


----------
For the moment, installation is a manual process. Please see the steps below to setup and run the CoProcessor on your selected Host platform

----------


Choose your platform:

	Smart Host:
	-------------------
	
1. Download and unzip a copy of this GitHub repository. For the remainder of this guide, I will assume you have downloaded it to your Downloads folder.
2. Copy the files to your Host using the following commands fromthe Terminal application (~/Applications/Utilities/Terminal):
		 A. `scp ~/Downloads/Hue-Savant-Coprocessor/coprocessor/hue-coprocessor.py RPM@192.168.14.50:hue-coprocessor.py`
		 B. `scp ~/Downloads/Hue-Savant-Coprocessor/coprocessor/smart/hue-coprocessor RPM@192.168.14.50:hue-coprocessor`
3. SSH into the host to preform the next steps. From Terminal again type:
`ssh RPM@192.168.14.50`
When prompted, enter your password (Default is 'RPM'). If you get an authenticity warning, just type 'yes'
4. Once logged in,  we need to have root privileges to preform the next steps. Get these by typing: `sudo su` This will prompt you for your password again. Now you should be identified as the root user
5. Now copy our two files to their appropriate location. To do this use the following commands:
	A. `cp hue-coprocessor.py /root/hue-coprocessor.py`
	B. `cp hue-coprocessor /etc/init.d/hue-coprocessor`
6. Move into the /etc/init.d directory with `cd /etc/init.d/`
7. now make sure that our CoProcessor starts when the host boots: 
`update-rc.d hue-coprocessor defaults`
8. Now we can start our CoProcessor:
`service hue-coprocessor start`

or

	Pro Host:
	-------------------


----------


Post Install Steps:
-------------------
After you have installed and started the CoProcessor you will need to press the Link button on your Philips Hue bridge for us to register a user with it.

As soon as the CoProcessor is started for the first time, it should discover your bridge on the network (as long as you have a working internet connection). If you have no internet, you will have to manually start the coprocessor at least once using the following command (substituting the IP address with that of your hosts):

`/root/hue-coprocessor.py -a 192.168.14.50`

If you also already know the API key you want to use you can pass this to the CoProcessor as well:

`/root/hue-coprocessor.py -a 192.168.14.50 -k <apikey>`

Once you have done that the CoProcessor will save the information in a settings file in the same location the script is kept. You can now stop this instance of the CoProcessor and restart the main one using the command listed in the installation steps above.
