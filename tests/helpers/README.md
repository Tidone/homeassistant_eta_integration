# Various helper scripts to manage the fixtures

All commands must be executed in the venv!

```
python3 -m venv venv
pip install -r requirements_test.txt
source venv/bin/activate
```

## Update API fixture

This script will connect to the ETA termnal, request the menu endpoint, and then loop through all available nodes and request their var and varinfo.\
The responses are then written to the `api_endpoint_data.json` fixture file.

```
/update_endpoint_data_fixture.py --host 192.168.0.25 --port 9091 --mode add-only -v
```

## Update sensor reference fixture

These scripts will execute the respective `_get_all_sensors_vxx` function from `api.py` while mocking the API calls to redirect them to the API fixture.\
The enumerated sensors are then written to the respective `api_assignment_reference_values_vxx.json` fixture file.

These scripts are used to update the fixture file if the sensor enumeration functions are updated. The fixture files are used in the unit tests, and because there are so many available sensors, updating the fixtures by hand is almost impossible.

**Note:** Use git to verify that the correct sensors have been updated/added/deleted!

```
./update_sensor_reference_v11.py --mode update -v
./update_sensor_reference_v12.py --mode update -v
```

## Convert fixture file to Unicode

This script will open the fixture file and replace all escaped unicode sequences (`\u...`) with the actual unicode characters.\
All fixture files have already been converted, so this script should not be needed any more.

```
./convert_unicode.py ../fixtures/v5_config_data.json
```