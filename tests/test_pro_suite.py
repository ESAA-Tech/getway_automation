"""
Comprehensive Test Suite for the Pro Gateway Orchestration Platform.
"""

import os
import json
import unittest

from pro.models.gateway import GatewayEntity, GatewayNetwork, GatewayAuth
from pro.models.device import DeviceConfig
from pro.models.datanode import RegisterPoint, DeviceProfile
from pro.core.diff_engine import DiffEngine
from pro.storage.inventory_repo import InventoryRepository
from pro.storage.backup_catalog import BackupCatalog
from pro.messaging.script_builder import ScriptBuilder
from pro.messaging.topics import build_device_topic, parse_device_topic
from pro.engine.rollout import RolloutEngine


class TestProPlatform(unittest.TestCase):

    def test_models_validation(self):
        gw = GatewayEntity(
            gateway_id="GW-TEST-01",
            network=GatewayNetwork(management_ip="192.168.4.1", management_port=80),
            auth=GatewayAuth(username="admin", password="password")
        )
        self.assertEqual(gw.gateway_id, "GW-TEST-01")
        self.assertEqual(gw.auth.get_effective_password(), "password")

        dev = DeviceConfig(
            plc_id="rgb_controller",
            channel="RS485-2",
            devtyp="PLC_MDBS_RTU",
            devaddr_str="1"
        )
        rpc_dict = dev.to_rpc_dict()
        self.assertEqual(rpc_dict["plc_id"], "rgb_controller")
        self.assertEqual(rpc_dict["channel"], "RS485-2")

    def test_profiles_loading(self):
        repo = InventoryRepository()
        profiles = repo.load_all_profiles()
        self.assertIn("rgb_controller_v1", profiles)
        self.assertIn("enviromental_sensor_v1", profiles)
        self.assertIn("smartpole_io_v1", profiles)

        rgb_prof = profiles["rgb_controller_v1"]
        self.assertEqual(rgb_prof.profile_id, "rgb_controller_v1")
        self.assertTrue(len(rgb_prof.registers) >= 6)

    def test_diff_engine(self):
        desired_devices = [
            DeviceConfig(plc_id="Screen", channel="ethernet", devtyp="PLC_FF_BOX", devaddr_str="0"),
            DeviceConfig(plc_id="rgb_controller", channel="RS485-2", devtyp="PLC_MDBS_RTU", devaddr_str="1")
        ]
        actual_devices = [
            {"plc_id": "Screen", "channel": "ethernet", "devtyp": "PLC_FF_BOX", "devaddr_str": "0", "chn_en": True, "ipaddr": "", "port": 0, "acq_intv": 500, "acqtimeout": 1000},
            {"plc_id": "enviromental", "channel": "RS485-1", "devtyp": "PLC_MDBS_RTU", "devaddr_str": "255", "chn_en": True, "ipaddr": "", "port": 0, "acq_intv": 500, "acqtimeout": 1000}
        ]

        to_add, to_update, to_remove, unchanged = DiffEngine.compute_device_diff(
            desired_devices, actual_devices, allow_prune=False
        )

        # rgb_controller should be added
        self.assertEqual(len(to_add), 1)
        self.assertEqual(to_add[0]["plc_id"], "rgb_controller")

        # Screen should be unchanged
        self.assertEqual(len(unchanged), 1)
        self.assertEqual(unchanged[0]["plc_id"], "Screen")

        # enviromental should NOT be removed because allow_prune is False
        self.assertEqual(len(to_remove), 0)

    def test_messaging_script_builder(self):
        # 1. Test topic builder and parser directly
        t = build_device_topic("site-downtown", "P-104", "lamp", "L-01", "cmd", "control")
        self.assertEqual(t, "scmp/v1/site-downtown/P-104/lamp/L-01/cmd/control")

        parsed = parse_device_topic(t)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["site_id"], "site-downtown")
        self.assertEqual(parsed["pole_code"], "P-104")
        self.assertEqual(parsed["device_type"], "lamp")
        self.assertEqual(parsed["device_id"], "L-01")
        self.assertEqual(parsed["direction"], "cmd")
        self.assertEqual(parsed["action"], "control")

        # 2. Test standard scripts generation matching SCMP backend architecture
        script_up, script_down = ScriptBuilder.build_standard_scripts(
            pole_id="P04-POLE1",
            site_id="site-riyadh-01"
        )
        self.assertEqual(len(script_up), 5)
        self.assertEqual(len(script_down), 2)

        up_ids = [s["script_id"] for s in script_up]
        self.assertIn("EnvTelemetry", up_ids)
        self.assertIn("PoleIoTelemetry", up_ids)
        self.assertIn("RgbTelemetry", up_ids)
        self.assertIn("CameraFault", up_ids)
        self.assertIn("ScreenFault", up_ids)

        env_script = next(s for s in script_up if s["script_id"] == "EnvTelemetry")
        self.assertEqual(env_script["event"], "scmp/v1/site-riyadh-01/P04-POLE1/env/env-01/telemetry")
        self.assertTrue(len(env_script["code"]) > 100)

        io_script = next(s for s in script_up if s["script_id"] == "PoleIoTelemetry")
        self.assertEqual(io_script["event"], "scmp/v1/site-riyadh-01/P04-POLE1/gateway/gw-01/status")

        rgb_script = next(s for s in script_up if s["script_id"] == "RgbTelemetry")
        self.assertEqual(rgb_script["event"], "scmp/v1/site-riyadh-01/P04-POLE1/rgb/rgb-01/telemetry")

        lamp_script = next(s for s in script_down if s["script_id"] == "LampControl")
        self.assertEqual(lamp_script["event"], "scmp/v1/site-riyadh-01/P04-POLE1/lamp/lamp-01/cmd/control")

        rgb_cmd_script = next(s for s in script_down if s["script_id"] == "RgbControl")
        self.assertEqual(rgb_cmd_script["event"], "scmp/v1/site-riyadh-01/P04-POLE1/rgb/rgb-01/cmd/control")

    def test_exact_scripts_testserver_and_test(self):
        # 1. Verify exact testserver scripts (24 UP, 5 DOWN)
        ts_up, ts_down = ScriptBuilder.load_exact_scripts(source="testserver")
        self.assertEqual(len(ts_up), 24)
        self.assertEqual(len(ts_down), 5)
        self.assertIn("Publish", [s["script_id"] for s in ts_up])
        self.assertIn("Temperature", [s["script_id"] for s in ts_up])
        self.assertIn("Noise", [s["script_id"] for s in ts_up])
        self.assertIn("LampControlTopic", [s["script_id"] for s in ts_down])
        self.assertIn("LedScreenControl", [s["script_id"] for s in ts_down])

        # Verify SCMP topic format for env, camera, and screen
        temp_s = next(s for s in ts_up if s["script_id"] == "Temperature")
        self.assertEqual(temp_s["event"], "scmp/v1/5efa910f-8e17-4443-af76-8b0a674d23f5/Pole-CBD-3444/env/29748b52-5203-49de-8221-7f9df657e28e/telemetry")

        noise_s = next(s for s in ts_up if s["script_id"] == "Noise")
        self.assertEqual(noise_s["event"], "scmp/v1/5efa910f-8e17-4443-af76-8b0a674d23f5/Pole-CBD-3444/env/29748b52-5203-49de-8221-7f9df657e28e/telemetry")

        cam_s = next(s for s in ts_up if s["script_id"] == "camera_status")
        self.assertEqual(cam_s["event"], "scmp/v1/5efa910f-8e17-4443-af76-8b0a674d23f5/Pole-CBD-3444/camera/camera-01/status")

        screen_s = next(s for s in ts_up if s["script_id"] == "led_screen_status")
        self.assertEqual(screen_s["event"], "scmp/v1/5efa910f-8e17-4443-af76-8b0a674d23f5/Pole-CBD-3444/screen/screen-01/status")

        # 2. Verify exact test scripts (20 UP, 5 DOWN)
        test_up, test_down = ScriptBuilder.load_exact_scripts(source="test")
        self.assertEqual(len(test_up), 20)
        self.assertEqual(len(test_down), 5)
        self.assertIn("Publish", [s["script_id"] for s in test_up])
        self.assertIn("Temperature", [s["script_id"] for s in test_up])
        self.assertIn("Fault", [s["script_id"] for s in test_up])
        self.assertIn("ScreenFault", [s["script_id"] for s in test_up])
        self.assertIn("Led", [s["script_id"] for s in test_down])
        self.assertIn("Strip", [s["script_id"] for s in test_down])
        self.assertIn("LampControl", [s["script_id"] for s in test_down])

        cam_test = next(s for s in test_up if s["script_id"] == "Fault")
        self.assertEqual(cam_test["event"], "scmp/v1/5efa910f-8e17-4443-af76-8b0a674d23f5/Pole-CBD-3444/camera/camera-01/status")

    def test_preflight_lint(self):
        engine = RolloutEngine()
        valid_gateways = [
            {"gateway_id": "GW-01", "ip_address": "192.168.4.1"},
            {"gateway_id": "GW-02", "ip_address": "192.168.4.2"}
        ]
        devices_map = {
            "GW-01": [DeviceConfig(plc_id="env", channel="RS485-1", devtyp="PLC_MDBS_RTU", devaddr_str="255")],
            "GW-02": [DeviceConfig(plc_id="env", channel="RS485-1", devtyp="PLC_MDBS_RTU", devaddr_str="255")]
        }
        errs = engine.run_preflight_lint(valid_gateways, devices_map)
        self.assertEqual(len(errs), 0)

        # Test duplicate gateway IP detection
        invalid_gateways = [
            {"gateway_id": "GW-01", "ip_address": "192.168.4.1"},
            {"gateway_id": "GW-02", "ip_address": "192.168.4.1"}
        ]
        errs_dupe = engine.run_preflight_lint(invalid_gateways, devices_map)
        self.assertTrue(any("Duplicate IP" in e for e in errs_dupe))


if __name__ == "__main__":
    unittest.main()
