"""Test SyncNetworkData diffsync models (software version handling)."""

from diffsync import exceptions as diffsync_exceptions
from nautobot.core.testing import TransactionTestCase
from nautobot.dcim.models import Device, SoftwareVersion
from nautobot.extras.models import JobResult

from nautobot_device_onboarding.diffsync.adapters.sync_network_data_adapters import SyncNetworkDataNautobotAdapter
from nautobot_device_onboarding.diffsync.models.sync_network_data_models import (
    SyncNetworkSoftwareToDevice,
    SyncNetworkSoftwareVersion,
)
from nautobot_device_onboarding.jobs import SSOTSyncDevices
from nautobot_device_onboarding.tests import utils


class SyncNetworkSoftwareVersionTestCase(TransactionTestCase):
    """Test the SyncNetworkSoftwareVersion model create/delete logic."""

    databases = ("default", "job_logs")

    def setUp(self):  # pylint: disable=invalid-name
        """Initialize test case."""
        self.testing_objects = utils.sync_network_data_ensure_required_nautobot_objects()

        self.job = SSOTSyncDevices()
        self.job.job_result = JobResult.objects.create(
            name=self.job.class_path, user=None, task_name="fake task", worker="default"
        )
        self.adapter = SyncNetworkDataNautobotAdapter(job=self.job, sync=None)

    def test_create__success(self):
        """A SoftwareVersion is created in Nautobot for a known platform."""
        ids = {"version": "16.12.04", "platform__name": self.testing_objects["platform_1"].name}
        SyncNetworkSoftwareVersion.create(adapter=self.adapter, ids=ids, attrs={})

        software_version = SoftwareVersion.objects.get(
            version="16.12.04", platform=self.testing_objects["platform_1"]
        )
        self.assertEqual("16.12.04", software_version.version)
        self.assertEqual(self.testing_objects["platform_1"].name, software_version.platform.name)
        self.assertEqual("Active", software_version.status.name)

    def test_create__platform_not_found(self):
        """Creating against a missing platform raises ObjectNotCreated and creates nothing."""
        ids = {"version": "16.12.04", "platform__name": "platform-does-not-exist"}
        with self.assertRaises(diffsync_exceptions.ObjectNotCreated):
            SyncNetworkSoftwareVersion.create(adapter=self.adapter, ids=ids, attrs={})
        self.assertFalse(SoftwareVersion.objects.filter(version="16.12.04").exists())

    def test_delete__is_prevented(self):
        """delete() is a no-op; the SoftwareVersion is never removed from Nautobot."""
        software_version = SoftwareVersion.objects.create(
            version="16.12.04",
            platform=self.testing_objects["platform_1"],
            status=self.testing_objects["status"],
        )
        model = SyncNetworkSoftwareVersion(
            version="16.12.04", platform__name=self.testing_objects["platform_1"].name
        )
        self.adapter.add(model)

        self.assertIsNone(model.delete())
        self.assertTrue(SoftwareVersion.objects.filter(pk=software_version.pk).exists())


class SyncNetworkSoftwareToDeviceTestCase(TransactionTestCase):
    """Test the SyncNetworkSoftwareToDevice model create/update/delete logic."""

    databases = ("default", "job_logs")

    def setUp(self):  # pylint: disable=invalid-name
        """Initialize test case."""
        self.testing_objects = utils.sync_network_data_ensure_required_nautobot_objects()

        self.job = SSOTSyncDevices()
        self.job.job_result = JobResult.objects.create(
            name=self.job.class_path, user=None, task_name="fake task", worker="default"
        )
        self.adapter = SyncNetworkDataNautobotAdapter(job=self.job, sync=None)

        self.device = self.testing_objects["device_1"]
        # A software version that is valid for device_1's platform.
        self.software_version = SoftwareVersion.objects.create(
            version="16.12.04",
            platform=self.device.platform,
            status=self.testing_objects["status"],
        )

    def _build_model(self, name, serial):
        """Build a SyncNetworkSoftwareToDevice model wired to the adapter."""
        model = SyncNetworkSoftwareToDevice(name=name, serial=serial, software_version__version="")
        self.adapter.add(model)
        return model

    def test_create__is_prevented(self):
        """create() never creates a device and returns None."""
        result = SyncNetworkSoftwareToDevice.create(
            adapter=self.adapter,
            ids={"name": "demo-cisco-1", "serial": "9ABUXU581111"},
            attrs={"software_version__version": "16.12.04"},
        )
        self.assertIsNone(result)

    def test_update__success(self):
        """update() assigns the software version to an existing device."""
        model = self._build_model(name=self.device.name, serial=self.device.serial)
        model.update(attrs={"software_version__version": "16.12.04"})

        self.device.refresh_from_db()
        self.assertEqual(self.software_version, self.device.software_version)

    def test_update__software_version_not_found(self):
        """A missing software version raises ObjectNotUpdated."""
        model = self._build_model(name=self.device.name, serial=self.device.serial)
        with self.assertRaises(diffsync_exceptions.ObjectNotUpdated):
            model.update(attrs={"software_version__version": "99.99.99"})

    def test_update__device_not_found(self):
        """A missing device aborts the update.

        NOTE: ``_get_and_assign_software_version`` converts the Django
        ``ObjectDoesNotExist`` into ``diffsync_exceptions.ObjectNotCreated``
        before ``update``'s own ``except ObjectDoesNotExist`` can catch it, so
        ``ObjectNotCreated`` (rather than ``ObjectNotUpdated``) propagates. This
        pins the current behaviour; see the coverage report for the flagged
        inconsistency.
        """
        model = self._build_model(name="device-does-not-exist", serial="no-such-serial")
        with self.assertRaises(diffsync_exceptions.ObjectNotCreated):
            model.update(attrs={"software_version__version": "16.12.04"})

    def test_delete__is_prevented(self):
        """delete() is a no-op; the device is never removed from Nautobot."""
        model = self._build_model(name=self.device.name, serial=self.device.serial)
        self.assertIsNone(model.delete())
        self.assertTrue(Device.objects.filter(pk=self.device.pk).exists())
