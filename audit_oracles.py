import json, pathlib, sys, sysconfig
import numpy as np
mode, output = sys.argv[1], pathlib.Path(sys.argv[2])
assert sysconfig.get_platform() == 'win-arm64'
if mode.startswith('h5py'):
    import h5py
    x = np.arange(240, dtype=np.int32).reshape(40, 6)
    path = pathlib.Path('oracle.h5')
    with h5py.File(path, 'w') as f:
        g = f.create_group('group/nested')
        g.attrs['meaning'] = 'native ARM64'
        g.attrs['scale'] = np.float64(1.25)
        for compression in ['gzip', 'lzf', None]:
            ds = g.create_dataset(str(compression), data=x, compression=compression, chunks=(10,6), maxshape=(None,6))
            ds.attrs['units']='count'
        g.create_dataset('utf8', data=['héllo','世界'], dtype=h5py.string_dtype())
    with h5py.File(path,'r') as f:
        assert list(f)==['group']
        g=f['group/nested']
        assert g.attrs['meaning']=='native ARM64' and g.attrs['scale']==1.25
        for compression in ['gzip', 'lzf', None]:
            ds=g[str(compression)]
            assert ds.compression==compression and ds.dtype==x.dtype and ds.attrs['units']=='count'
            np.testing.assert_array_equal(ds[:],x)
            np.testing.assert_array_equal(ds[3:7,2:5],x[3:7,2:5])
        assert g['utf8'].asstr()[:].tolist()==['héllo','世界']
        try: np.testing.assert_array_equal(g['gzip'][:],x+1)
        except AssertionError: pass
        else: raise AssertionError('Poisoned expected data unexpectedly passed')
    (output/'oracles.json').write_text(json.dumps({'status':'PASS','version':h5py.__version__, 'hdf5_version':h5py.version.hdf5_version,'numpy':np.__version__,'coverage':['dataset','groups','attributes','gzip','lzf','chunks','slice','utf8','roundtrip','poisoned-oracle-negative']},indent=2))
else:
    import pandas as pd
    import fastparquet as fp
    import duckdb
    df=pd.DataFrame({'i':np.array([1,2,3,4],dtype='int32'),'f':[1.5,np.nan,3.5,4.5],'cat':pd.Categorical(['a','b',None,'a']),'text':pd.Series(['α',None,'c','d'],dtype=object),'nullable':pd.Series([1,None,3,4],dtype='Int64'),'flag':pd.Series([True,None,False,True],dtype='boolean'),'ts':pd.date_range('2024-01-01',periods=4)})
    outcomes=[]
    errors=[]
    for compression in ['GZIP','SNAPPY','ZSTD',None]:
        try:
            path=pathlib.Path(f'oracle-{compression}.parquet')
            fp.write(path,df,compression=compression,row_group_offsets=[0,2],write_index=False)
            p=fp.ParquetFile(path)
            assert len(p.row_groups)==2
            independent=duckdb.connect().execute('SELECT i, f, cat, text, nullable, flag FROM read_parquet(?) ORDER BY i',[str(path)]).fetchall()
            assert independent==[(1,1.5,'a','α',1,True),(2,None,'b',None,None,None),(3,3.5,None,'c',3,False),(4,4.5,'a','d',4,True)],independent
            outcomes.append({'compression':compression,'gate':'independent-DuckDB-read','status':'PASS','row_groups':2})
            actual=p.to_pandas()
            pd.testing.assert_frame_equal(actual,df)
            try: pd.testing.assert_frame_equal(actual,df.assign(i=df.i+1))
            except AssertionError: pass
            else: raise AssertionError('Poisoned oracle did not fail')
            outcomes.append({'compression':compression,'status':'PASS','row_groups':2})
        except Exception as exc:
            errors.append({'compression':compression,'type':type(exc).__name__,'message':str(exc)})
    (output/'oracles.json').write_text(json.dumps({'status':'FAIL' if errors else 'PASS','fastparquet':fp.__version__,'numpy':np.__version__,'pandas':pd.__version__,'duckdb':duckdb.__version__,'independent_reader':'DuckDB native ARM64; PyArrow CP312 ARM64 unavailable on PyPI','cases':outcomes,'errors':errors},indent=2))
    assert not errors, errors
