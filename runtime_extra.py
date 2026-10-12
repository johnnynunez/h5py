import ctypes, ctypes.wintypes as w, hashlib, json, pathlib, sys, sysconfig
out=pathlib.Path(sys.argv[1]); mode=sys.argv[2]
assert sysconfig.get_platform()=='win-arm64'
import numpy
if mode=='h5py':
    import h5py
else:
    import pandas, fastparquet, duckdb
psapi=ctypes.WinDLL('psapi'); kernel=ctypes.WinDLL('kernel32')
kernel.GetCurrentProcess.restype=w.HANDLE
handle=kernel.GetCurrentProcess()
modules=(w.HMODULE*4096)(); needed=w.DWORD()
psapi.EnumProcessModules.argtypes=[w.HANDLE,ctypes.POINTER(w.HMODULE),w.DWORD,ctypes.POINTER(w.DWORD)]
psapi.GetModuleFileNameExW.argtypes=[w.HANDLE,w.HMODULE,w.LPWSTR,w.DWORD]
assert psapi.EnumProcessModules(handle,modules,ctypes.sizeof(modules),ctypes.byref(needed))
rows=[]
for mod in modules[:needed.value//ctypes.sizeof(w.HMODULE)]:
    buf=ctypes.create_unicode_buffer(32768)
    assert psapi.GetModuleFileNameExW(handle,mod,buf,len(buf))
    p=pathlib.Path(buf.value)
    rows.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
(out/'loaded-modules.json').write_text(json.dumps(rows,indent=2))
assert any('vcruntime' in r['path'].lower() for r in rows)
assert not any('native-prefix' in r['path'].lower() for r in rows)
if mode=='h5py':
    import numpy as np, zlib
    assert h5py.__version__=='3.12.1+np2556.arm64.1'
    assert h5py.version.hdf5_version=='1.14.2'
    assert any('hdf5' in r['path'].lower() for r in rows)
    a=np.arange(60,dtype=np.int32).reshape(10,6)
    with h5py.File('codec.h5','w') as f:
        d=f.create_dataset('gzip',data=a,chunks=a.shape,compression='gzip')
        mask,chunk=d.id.read_direct_chunk((0,0))
        assert mask==0
        assert zlib.decompress(chunk)==a.tobytes()
        d=f.create_dataset('checksum',data=a,chunks=a.shape,fletcher32=True)
        mask,chunk=d.id.read_direct_chunk((0,0))
        bad=bytes([chunk[0]^1])+chunk[1:]
        d.id.write_direct_chunk((0,0),bad,filter_mask=mask)
    with h5py.File('codec.h5','r') as f:
        try: f['checksum'][:]
        except OSError: pass
        else: raise AssertionError('Corrupt Fletcher32 chunk accepted')
    for name,data in [('bad-signature.h5',b'not HDF5'),('truncated.h5',pathlib.Path('codec.h5').read_bytes()[:32])]:
        pathlib.Path(name).write_bytes(data)
        try:
            with h5py.File(name,'r'): pass
        except OSError: pass
        else: raise AssertionError('Malformed HDF5 accepted: '+name)
    (out/'codec-malformed.json').write_text(json.dumps({'status':'PASS','coverage':['independent-zlib-decode-exact-chunk','corrupt-Fletcher32-rejected','bad-signature-rejected','truncated-file-rejected','loaded-HDF5-1.14.2','loaded-CRT-paths-hashes']},indent=2))
print('Loaded module witnesses and extra gates PASS')
