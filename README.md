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