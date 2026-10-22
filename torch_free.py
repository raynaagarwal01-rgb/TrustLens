"""torch_free.py — read a PyTorch checkpoint (legacy or zip format) into numpy arrays without installing PyTorch."""

import io
import pickle
import struct
import zipfile

import numpy as np

DTYPES = {"FloatStorage": np.float32, "HalfStorage": np.float16, "DoubleStorage": np.float64,
          "LongStorage": np.int64, "IntStorage": np.int32, "ByteStorage": np.uint8, "BoolStorage": np.bool_}


class _StorageType:
    def __init__(self, name):
        self.dtype = DTYPES.get(name, np.float32)


def _rebuild_tensor(storage, offset, size, stride, *_):
    arr = storage
    if not size:
        return arr[offset:offset + 1].reshape(()).copy()
    itemsize = arr.dtype.itemsize
    return np.lib.stride_tricks.as_strided(arr[offset:], shape=tuple(size),
                                          strides=tuple(s * itemsize for s in stride)).copy()


class _Unpickler(pickle.Unpickler):
    def __init__(self, f, load_storage):
        super().__init__(f)
        self._load_storage = load_storage

    def find_class(self, module, name):
        if module == "torch._utils" and name in ("_rebuild_tensor_v2", "_rebuild_tensor"):
            return _rebuild_tensor
        if module == "torch" and name.endswith("Storage"):
            return _StorageType(name)
        if module == "collections" and name == "OrderedDict":
            import collections
            return collections.OrderedDict
        if module.startswith("torch"):
            return lambda *a, **k: None
        return super().find_class(module, name)

    def persistent_load(self, pid):
        return self._load_storage(pid)


def load(path) -> dict:
    """Returns the checkpoint's state dict as {name: numpy array}."""
    if zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        root = z.namelist()[0].split("/")[0]

        def storage(pid):
            _, stype, key, _loc, _n = pid[:5]
            return np.frombuffer(z.read(f"{root}/data/{key}"), dtype=stype.dtype)

        obj = _Unpickler(io.BytesIO(z.read(f"{root}/data.pkl")), storage).load()
    else:
        # legacy format: 3 header pickles, the object pickle, the storage key list, then raw storages.
        # The raw bytes come after the object, so read the object once to learn the storage types,
        # then again with the bytes in hand.
        f = open(path, "rb")
        for _ in range(3):  # magic number, protocol version, system info
            pickle.load(f)
        start = f.tell()
        types = {}

        def note_type(pid):
            types[pid[2]] = pid[1].dtype
            return np.zeros(0, dtype=pid[1].dtype)

        class _Skim(_Unpickler):
            def find_class(self, module, name):
                if module == "torch._utils" and name.startswith("_rebuild_tensor"):
                    return lambda *a, **k: None
                return super().find_class(module, name)

        _Skim(f, note_type).load()
        raw = {}
        for key in pickle.load(f):
            n = struct.unpack("<q", f.read(8))[0]
            raw[key] = np.frombuffer(f.read(n * np.dtype(types[key]).itemsize), dtype=types[key])
        f.seek(start)
        obj = _Unpickler(f, lambda pid: raw[pid[2]]).load()
    sd = obj.get("state_dict", obj) if isinstance(obj, dict) else obj
    return {k.removeprefix("module."): v for k, v in sd.items() if isinstance(v, np.ndarray)}
