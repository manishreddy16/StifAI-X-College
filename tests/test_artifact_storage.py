from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api.artifact_storage import (
    LocalArtifactStorage,
    S3ArtifactStorage,
    StorageConfigurationError,
    StorageError,
    get_storage,
    storage_backend,
)


class _MissingObject(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}


class _FakeS3:
    def __init__(self):
        self.objects = {}

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise _MissingObject()

    def upload_file(self, filename, bucket, key):
        self.objects[key] = Path(filename).read_bytes()

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.objects[Key] = bytes(Body)

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise _MissingObject()
        return {"Body": io.BytesIO(self.objects[Key])}

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[key])


class _FakeConnection:
    def lock_key(self, key):
        assert key == "stif-campus-ai:artifact-manifest"


class ArtifactStorageTests(unittest.TestCase):
    def test_local_default_and_explicit_invalid_configuration(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(storage_backend(), "local")
            self.assertIsInstance(get_storage(), LocalArtifactStorage)
        with mock.patch.dict("os.environ", {"STIF_STORAGE_BACKEND": "mystery"}, clear=True):
            with self.assertRaises(StorageConfigurationError):
                storage_backend()

    def test_explicit_r2_without_private_configuration_fails_instead_of_using_local(self):
        with mock.patch.dict("os.environ", {"STIF_STORAGE_BACKEND": "r2"}, clear=True):
            self.assertEqual(storage_backend(), "r2")
            with self.assertRaisesRegex(StorageConfigurationError, "STIF_STORAGE_BUCKET"):
                get_storage()

    def test_seed_and_materialize_generation_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            (root / "index_fast").mkdir(parents=True)
            original = b'{"text":"SVCE Tirupati synthetic test"}\n'
            (root / "index_fast" / "chunks.jsonl").write_bytes(original)
            client = _FakeS3()
            storage = S3ArtifactStorage(client, bucket="fixture", prefix="test", data_root=root)
            session = mock.MagicMock()
            session.__enter__.return_value = _FakeConnection()
            with (
                mock.patch("api.db.database_backend", return_value="postgres"),
                mock.patch("api.db.session", return_value=session),
                mock.patch("api.db.transaction") as transaction,
            ):
                transaction.return_value.__enter__.return_value = None
                result = storage.publish_local(allow_initial=True)
            self.assertEqual(result["files"], 1)
            self.assertTrue(storage.check_ready())
            (root / "index_fast" / "chunks.jsonl").write_bytes(b"stale local copy")
            hydrated = storage.materialize_active()
            self.assertEqual(hydrated["generation"], result["generation"])
            self.assertEqual((root / "index_fast" / "chunks.jsonl").read_bytes(), original)
            manifest = json.loads(client.objects["test/active.json"])
            self.assertEqual(manifest["generation"], result["generation"])

    def test_seed_refuses_storage_outage_and_missing_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            (root / "index").mkdir(parents=True)
            (root / "index" / "chunks.jsonl").write_text('{"text":"synthetic"}\n', encoding="utf-8")
            client = _FakeS3()
            client.head_object = mock.Mock(side_effect=RuntimeError("private remote details"))
            storage = S3ArtifactStorage(client, bucket="fixture", prefix="test", data_root=root)
            session = mock.MagicMock()
            session.__enter__.return_value = _FakeConnection()
            with (
                mock.patch("api.db.database_backend", return_value="postgres"),
                mock.patch("api.db.session", return_value=session),
                mock.patch("api.db.transaction") as transaction,
            ):
                transaction.return_value.__enter__.return_value = None
                with self.assertRaises(StorageError):
                    storage.publish_local(allow_initial=True)
            self.assertEqual(client.objects, {})

    def test_stale_instance_cannot_replace_a_newer_active_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            index = root / "index"
            index.mkdir(parents=True)
            target = index / "chunks.jsonl"
            target.write_text('{"text":"synthetic original"}\n', encoding="utf-8")
            client = _FakeS3()
            first = S3ArtifactStorage(client, bucket="fixture", prefix="test", data_root=root)
            second = S3ArtifactStorage(client, bucket="fixture", prefix="test", data_root=root)
            session = mock.MagicMock()
            session.__enter__.return_value = _FakeConnection()
            with (
                mock.patch("api.db.database_backend", return_value="postgres"),
                mock.patch("api.db.session", return_value=session),
                mock.patch("api.db.transaction") as transaction,
            ):
                transaction.return_value.__enter__.return_value = None
                seeded = first.publish_local(allow_initial=True)
                second.materialize_active()
                target.write_text('{"text":"newer synthetic generation"}\n', encoding="utf-8")
                advanced = first.publish_local()
                self.assertNotEqual(seeded["generation"], advanced["generation"])
                with self.assertRaisesRegex(StorageError, "generation changed"):
                    second.publish_local()

    def test_manifest_path_escape_and_checksum_corruption_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            root.mkdir()
            client = _FakeS3()
            storage = S3ArtifactStorage(client, bucket="fixture", prefix="test", data_root=root)
            client.objects["test/active.json"] = json.dumps({
                "version": 1, "generation": "a" * 32,
                "files": [{"path": "../secret", "key": "x", "size": 0, "sha256": "0" * 64}],
            }).encode()
            with self.assertRaises(StorageError):
                storage.materialize_active()


if __name__ == "__main__":
    unittest.main()
