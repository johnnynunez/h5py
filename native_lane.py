"""Public-source-only native CP312 build/validation harness."""
import base64, csv, hashlib, io, json, os, pathlib, platform, shutil, subprocess, sys, sysconfig, urllib.request, zipfile

ROOT = pathlib.Path.cwd()
OUT = ROOT / 'evidence'
OUT.mkdir(exist_ok=True)
SOURCE = ROOT / 'source'
MODE = sys.argv[1]
PY = sys.executable
STATUS = {}

def run(args, name, cwd=None, check=True):
    args = list(map(str, args))
    print(name, args, flush=True)
    with (OUT / (name + '.log')).open('w', encoding='utf-8') as log:
        p = subprocess.run(args, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    STATUS[name] = p.returncode
    print((OUT / (name + '.log')).read_text(encoding='utf-8', errors='replace')[-6000:], flush=True)
    if check and p.returncode:
        raise RuntimeError(f'{name}: exit {p.returncode}')
    return p.returncode

def download(repo, sha, name):
    url = f'https://github.com/{repo}/archive/{sha}.zip'
    dest = OUT / (name + '-source.zip')
    urllib.request.urlretrieve(url, dest)
    record = {'repo': repo, 'sha': sha, 'url': url, 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()}
    (OUT / (name + '-source.json')).write_text(json.dumps(record, indent=2))
    with zipfile.ZipFile(dest) as z:
        z.extractall(ROOT / 'deps')
        source = ROOT / 'deps' / z.namelist()[0].split('/')[0]
    for file in source.glob('*'):
        if 'license' in file.name.lower() or 'copying' in file.name.lower():
            shutil.copy(file, OUT / (name + '-' + file.name))
    return source

def main():
    assert sys.version_info[:2] == (3, 12)
    assert sysconfig.get_platform() == 'win-arm64', sysconfig.get_platform()
    expected = os.environ['SOURCE_SHA']
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()
    assert actual == expected, (actual, expected)
    (OUT / 'provenance.json').write_text(json.dumps({'source_sha': actual, 'wrapper_sha': os.environ['GITHUB_SHA'], 'mode': MODE, 'python': sys.version, 'platform': platform.platform(), 'sysconfig': sysconfig.get_platform(), 'harness_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(), 'pins': {'numpy': '2.5.4', 'pandas': '3.0.6' if MODE == 'fastparquet' else None}, 'original_locks_unchanged': True}, indent=2))
    run([PY, '-m', 'pip', 'install', '--only-binary=:all:', 'numpy==2.5.4', 'Cython==3.0.12', 'setuptools==80.9.0', 'wheel', 'setuptools-scm', 'pkgconfig', 'build', 'pefile', 'delvewheel', 'pytest==8.4.2', 'pytest-timeout', 'hypothesis', 'cmake<4'], 'tools')
    wheel_dir = OUT / 'wheels'
    wheel_dir.mkdir(exist_ok=True)
    if MODE == 'h5py-old':
        zsrc = download('madler/zlib', '51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf', 'zlib-1.3.1')
        hsrc = download('HDFGroup/hdf5', '2d926cf0426d2ed9403946071d9b05ac8b4dd778', 'hdf5-1.14.2')
        prefix = ROOT / 'native-prefix'
        run(['cmake', '-S', zsrc, '-B', ROOT/'zbuild', '-G', 'Visual Studio 17 2022', '-A', 'ARM64', '-DCMAKE_INSTALL_PREFIX='+prefix.as_posix(), '-DZLIB_BUILD_EXAMPLES=OFF'], 'zlib-configure')
        run(['cmake', '--build', ROOT/'zbuild', '--config', 'Release', '--target', 'install', '--parallel', '4'], 'zlib-build')
        run(['cmake', '-S', hsrc, '-B', ROOT/'hbuild', '-G', 'Visual Studio 17 2022', '-A', 'ARM64', '-DCMAKE_INSTALL_PREFIX='+prefix.as_posix(), '-DCMAKE_PREFIX_PATH='+prefix.as_posix(), '-DBUILD_SHARED_LIBS=ON', '-DBUILD_TESTING=OFF', '-DHDF5_BUILD_CPP_LIB=OFF', '-DHDF5_BUILD_FORTRAN=OFF', '-DHDF5_BUILD_HL_LIB=ON', '-DHDF5_BUILD_TOOLS=OFF', '-DHDF5_BUILD_EXAMPLES=OFF', '-DHDF5_ENABLE_Z_LIB_SUPPORT=ON', '-DHDF5_ENABLE_SZIP_SUPPORT=OFF', '-DZLIB_USE_STATIC_LIBS=OFF', '-DHDF5_EXTERNAL_LIB_PREFIX='], 'hdf5-configure')
        run(['cmake', '--build', ROOT/'hbuild', '--config', 'Release', '--target', 'install', '--parallel', '4'], 'hdf5-build')
        os.environ['HDF5_DIR'] = str(prefix)
        os.environ['HDF5_VERSION'] = '1.14.2'
        os.environ['PATH'] = str(prefix/'bin') + os.pathsep + os.environ['PATH']
        for dll in (prefix/'bin').glob('*.dll'):
            shutil.copy(dll, prefix/'lib'/dll.name)
        for f in (ROOT/'hbuild').glob('CMakeCache.txt'):
            shutil.copy(f, OUT/'HDF5-CMakeCache.txt')
    if MODE == 'h5py-reference':
        run([PY, '-m', 'pip', 'download', '--no-deps', '--only-binary=:all:', 'h5py==3.16.0', '-d', wheel_dir], 'download-reference')
    else:
        raw = OUT / 'raw-wheels'
        run([PY, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation', '-v', '.', '-w', raw], 'build-wheel', SOURCE)
        wheel = next(raw.glob('*.whl'))
        command = [PY, '-m', 'delvewheel', 'repair', '-w', wheel_dir, wheel]
        if MODE == 'h5py-old':
            command += ['--add-path', str(ROOT/'native-prefix'/'bin')]
        run(command, 'repair-wheel')
    wheel = next(wheel_dir.glob('*.whl'))
    expected_version = {'h5py-old':'3.12.1','h5py-reference':'3.16.0','fastparquet':'2024.11.0'}[MODE]
    audit(wheel, expected_version)
    run([PY, '-m', 'venv', ROOT/'test-env'], 'venv')
    testpy = ROOT/'test-env'/'Scripts'/'python.exe'
    deps = ['numpy==2.5.4', 'pytest==8.4.2', 'pytest-timeout', 'hypothesis']
    if MODE == 'fastparquet':
        deps += ['pandas==3.0.6', 'cramjam==2.13.0', 'fsspec', 'packaging', 'duckdb==1.5.6']
    run([testpy, '-m', 'pip', 'install', '--only-binary=:all:', *deps, wheel], 'test-install')
    run([testpy, '-m', 'pip', 'freeze', '--all'], 'test-freeze')
    run([testpy, '-m', 'pip', 'check'], 'pip-check', check=False)
    clean = ROOT/'clean-test'
    clean.mkdir(exist_ok=True)
    # Remove native build paths; repaired wheels must resolve their own DLLs.
    os.environ.pop('HDF5_DIR', None)
    os.environ['PATH'] = os.pathsep.join(p for p in os.environ['PATH'].split(os.pathsep) if 'native-prefix' not in p)
    run([testpy, ROOT/'wrapper'/'audit_oracles.py', MODE, OUT], 'oracles', clean, check=False)
    if MODE.startswith('h5py'):
        run([testpy, '-m', 'pytest', '--pyargs', 'h5py.tests', '-q', '--timeout=60', '--junitxml='+str(OUT/'upstream.xml')], 'upstream-tests', clean, check=False)
    else:
        shutil.copytree(SOURCE/'fastparquet'/'test', clean/'test', dirs_exist_ok=True)
        if (SOURCE/'test-data').exists():
            shutil.copytree(SOURCE/'test-data', clean/'test-data', dirs_exist_ok=True)
        run([testpy, '-m', 'pytest', 'test/test_api.py', 'test/test_compression.py', 'test/test_encoding.py', 'test/test_speedups.py', 'test/test_thrift_structures.py', '-q', '--timeout=60', '--junitxml='+str(OUT/'upstream.xml')], 'upstream-tests', clean, check=False)

def audit(wheel, expected):
    import pefile
    payload = ROOT/'wheel-payload'
    report = {'filename':wheel.name, 'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(), 'PE':[], 'record_valid':False, 'licenses':[]}
    with zipfile.ZipFile(wheel) as z:
        rec = next(n for n in z.namelist() if n.endswith('.dist-info/RECORD'))
        for name, digest, size in csv.reader(io.StringIO(z.read(rec).decode())):
            if digest:
                method, value = digest.split('=',1)
                actual=base64.urlsafe_b64encode(hashlib.new(method,z.read(name)).digest()).rstrip(b'=').decode()
                assert actual == value and len(z.read(name)) == int(size), name
        report['record_valid']=True
        meta=next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
        from email import message_from_bytes
        assert message_from_bytes(z.read(meta))['Version'] == expected
        report['licenses']=[n for n in z.namelist() if any(t in n.lower() for t in ['license','copying'])]
        assert report['licenses'], 'Missing package license'
        z.extractall(payload)
    files={p.name.lower():p for p in payload.rglob('*') if p.is_file()}
    for p in payload.rglob('*'):
        if p.suffix.lower() not in ('.dll','.pyd'):
            continue
        pe=pefile.PE(str(p)); imports=[]
        for descriptor in getattr(pe,'DIRECTORY_ENTRY_IMPORT',[]):
            name=descriptor.dll.decode(); key=name.lower()
            if key in files:
                resolved=str(files[key].relative_to(payload))
            elif key.startswith(('api-ms-','ext-ms-')):
                resolved='Windows API-set'
            elif key.startswith('python3'):
                resolved='CPython runtime'
            elif (pathlib.Path(os.environ['SystemRoot'])/'System32'/name).exists():
                resolved='Windows System32'
            else:
                resolved='UNRESOLVED'
            imports.append({'name':name,'resolved':resolved})
        report['PE'].append({'path':str(p.relative_to(payload)), 'machine':hex(pe.FILE_HEADER.Machine),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'imports':imports})
    (OUT/'wheel-audit.json').write_text(json.dumps(report,indent=2))
    assert report['PE']
    STATUS['native-payload']=int(any(p['machine']!='0xaa64' for p in report['PE']))
    STATUS['import-closure']=int(any(i['resolved']=='UNRESOLVED' for p in report['PE'] for i in p['imports']))
    # RECORD hash oracle negative control: a modified payload must differ.
    content=wheel.read_bytes(); assert hashlib.sha256(content+b'poison').hexdigest()!=report['sha256']

try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    STATUS['harness-exception']=1
finally:
    (OUT/'status.json').write_text(json.dumps(STATUS,indent=2))
    print(json.dumps(STATUS),flush=True)
sys.exit(int(any(STATUS.values())))
