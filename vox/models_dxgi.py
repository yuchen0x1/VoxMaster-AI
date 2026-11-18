"""Query the same DXGI adapter enumeration used by the DirectML provider."""

import ctypes as ct
import uuid
from ctypes import wintypes as wt


class AdapterDesc(ct.Structure):
    _fields_ = [
        ("Description", wt.WCHAR * 128),
        ("VendorId", wt.UINT),
        ("DeviceId", wt.UINT),
        ("SubSysId", wt.UINT),
        ("Revision", wt.UINT),
        ("DedicatedVideoMemory", ct.c_size_t),
        ("DedicatedSystemMemory", ct.c_size_t),
        ("SharedSystemMemory", ct.c_size_t),
        ("AdapterLuid", ct.c_int64),
    ]


class VideoMemory(ct.Structure):
    _fields_ = [
        (name, ct.c_uint64)
        for name in ("Budget", "CurrentUsage", "AvailableForReservation", "CurrentReservation")
    ]


def guid(value):
    return (ct.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le)


def method(obj, index, result, *arguments):
    vtable = ct.cast(obj, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return ct.WINFUNCTYPE(result, ct.c_void_p, *arguments)(vtable[index])


def release(ptr):
    if ptr:
        method(ptr, 2, wt.ULONG)(ptr)


class DirectMLAdapter:
    def __init__(self, *, luid=None):
        value = ct.c_void_p()
        factory_iid = guid("7b7166ec-21c7-44ae-b21a-c9ae321ae369")
        if ct.windll.dxgi.CreateDXGIFactory(ct.byref(factory_iid), ct.byref(value)) < 0:
            raise OSError("无法枚举 DXGI 显卡")
        self.ptr = ct.c_void_p()
        self.index, self.name = 0, ""
        largest = -1
        try:
            enum = method(value, 7, wt.LONG, wt.UINT, ct.POINTER(ct.c_void_p))
            for index in range(64):
                adapter = ct.c_void_p()
                if enum(value, index, ct.byref(adapter)) < 0:
                    break
                try:
                    desc = AdapterDesc()
                    query = method(adapter, 8, wt.LONG, ct.POINTER(AdapterDesc))
                    if query(adapter, ct.byref(desc)) < 0 or desc.VendorId == 0x1414:
                        continue
                    if luid is not None and luid != desc.AdapterLuid:
                        continue
                    if desc.DedicatedVideoMemory <= largest:
                        continue
                    largest = desc.DedicatedVideoMemory
                    self.index, self.name = index, desc.Description
                    release(self.ptr)
                    self.ptr = ct.c_void_p()
                    iid = guid("645967a4-1392-4310-a798-8053ce3e93fd")
                    qi = method(adapter, 0, wt.LONG, ct.c_void_p, ct.POINTER(ct.c_void_p))
                    qi(adapter, ct.byref(iid), ct.byref(self.ptr))
                finally:
                    release(adapter)
        finally:
            release(value)
        if not self.name:
            raise OSError("未发现硬件 DXGI 适配器")

    def stats(self):
        if not self.ptr:
            return " · " + self.name
        video = VideoMemory()
        fn = method(self.ptr, 14, wt.LONG, wt.UINT, wt.UINT, ct.POINTER(VideoMemory))
        if fn(self.ptr, 0, 0, ct.byref(video)) >= 0:
            return (
                f" · {self.name} · 进程显存 {video.CurrentUsage // 1048576} MiB"
                f" / 预算 {video.Budget // 1048576} MiB"
            )
        return " · " + self.name

    def close(self):
        release(self.ptr)
        self.ptr = None


def cuda_adapter(ordinal=0):
    """Match CUDA's WDDM adapter to DXGI for per-process memory reporting."""
    try:
        driver = ct.WinDLL("nvcuda.dll", winmode=0x800)  # system32 only
        device, mask = ct.c_int(), ct.c_uint()
        luid = (ct.c_ubyte * 8)()
        if driver.cuInit(0) or driver.cuDeviceGet(ct.byref(device), ordinal):
            return None
        if driver.cuDeviceGetLuid(luid, ct.byref(mask), device):
            return None
        return DirectMLAdapter(luid=int.from_bytes(bytes(luid), "little", signed=True))
    except (OSError, AttributeError):
        return None
