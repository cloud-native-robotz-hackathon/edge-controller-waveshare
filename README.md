# edge-controller-waveshare
Setup for the Waveshare Rover (tested with Rasbian)

* Make sure to set in the Raspberry config > Interface Options > Serial Port
  * Login Shell = No
  * Serial Port Hardware = Yes

* Create Python env and run
  * python -m venv robo_env
  * source robo_env/bin/activate
  * pip install -r requirements.txt
  * python server.py

* API is available at localhost:5000

## TODOs
* Camera access needs to be teste
* Skupper connection
* Test with Fedora
* Microshift

## Skupper 

Setup Skupper between OCP and Raspi/Podman node

- Install RH Service Interconnect on OCP
- On OCP create project, download skupper cli (correct version) to laptop and do:
	- oc login
	- oc project
	- skupper init
	- skupper token create ocp-token.yaml
	- copy token file to Raspi
- On Raspi:
	- download skupper cli  (correct version) 
	- export SKUPPER_PLATFORM=podman
	- skupper init
	- skupper link create ocp-token.yaml
	- Check with skupper link status on both sides
	- Expose service running on 5000 (non Podman)
		- skupper expose host host.containers.internal --address <hostname> --port 5000
- On OCP from laptop
	- Expose the Skupper service as OCP service
		- skupper service create darklord 5000

Make sure service runs and test from OCP terminal, e.g.:
curl darklord.robot.svc.cluster.local:5000