#!/usr/bin/env python3
"""Independent stream-copy oracle plus file/gzip/TCP integration at O0/O3."""
from __future__ import annotations
import argparse
import hashlib
import json
import socket
import subprocess
import tempfile
import threading
import zlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def inputs():
    paths = list((ROOT/'src').rglob('*.xu'))
    paths += [Path(__file__), ROOT/'tests/oracles/io_stream.go', ROOT/'tests/drivers/io_stream.xu', ROOT/'scripts/run_product_compiler.sh']
    for name in ('io_stream_copy','gzip_stream_copy'):
        paths += list((ROOT/'tests/fixtures'/name).glob('*'))
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(paths) if p.is_file()}

def run(cmd):
    return subprocess.run(list(map(str,cmd)),cwd=ROOT,capture_output=True,timeout=60)

def compile_driver(xu,source,binary,opt):
    p=run([ROOT/'scripts/run_product_compiler.sh',xu,'build',source,'-'+opt,'-o',binary])
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors='replace'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xu',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    a=parser.parse_args();xu=a.xu.resolve()
    report=dict(compiler=str(xu),compiler_sha256=digest(xu),input_sha256=inputs(),results=[])
    def record(name,opt,passed,**detail):
        report['results'].append(dict(case=name,optimization=opt,passed=passed,**detail))
        print(('PASS' if passed else 'FAIL')+' '+name+' '+opt,flush=True)
    with tempfile.TemporaryDirectory(prefix='xu-stream-conformance-') as td:
        tmp=Path(td)
        oracle=run(['go','run','tests/oracles/io_stream.go'])
        report['go_version']=run(['go','version']).stdout.decode().strip()
        frozen=oracle.returncode==0 and oracle.stdout==(ROOT/'tests/fixtures/io_stream_copy/expected.txt').read_bytes()
        for opt in ('O0','O3'):
            for name in ('io_stream_copy','gzip_stream_copy'):
                f=ROOT/'tests/fixtures'/name
                binary=tmp/name
                compile_driver(xu,f/'main.xu',binary,opt)
                p=run([binary]);expected=(f/'expected.txt').read_bytes()
                record(name,opt,p.returncode==0 and p.stdout==expected and (frozen or name!='io_stream_copy'),stderr=p.stderr.decode(errors='replace'),stdout_sha256=hashlib.sha256(p.stdout).hexdigest())
            driver=tmp/'driver';compile_driver(xu,ROOT/'tests/drivers/io_stream.xu',driver,opt)
            for n in (0,1,4096,4097,65535,65536,1048593):
                data=(bytes(range(256))*((n+255)//256))[:n]
                source=tmp/'input';source.write_bytes(data)
                for mode in ('file','gzip'):
                    target=tmp/'output';p=run([driver,mode,source,target])
                    try:
                        raw=target.read_bytes();actual=zlib.decompress(raw,31) if mode=='gzip' else raw
                        if mode=='gzip':
                            dec=zlib.decompressobj(31);dec.decompress(raw);complete=dec.eof and not dec.unused_data
                        else:complete=True
                    except (OSError,zlib.error):actual=None;complete=False
                    record(mode+'-'+str(n),opt,p.returncode==0 and p.stdout==f'{n}\n'.encode() and actual==data and complete,stderr=p.stderr.decode(errors='replace'))
            # Server inspects/decompresses each received chunk incrementally;
            # payload includes NUL and all byte values, crossing block boundaries.
            data=(bytes(range(256))*4097)+b'tail';source=tmp/'input';source.write_bytes(data)
            wanted=hashlib.sha256(data).hexdigest()
            for mode in ('tcp','gzip-tcp','recv'):
                result={}
                listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(20)
                address='127.0.0.1:'+str(listener.getsockname()[1])
                def serve():
                    try:
                        with listener,listener.accept()[0] as conn:
                            conn.settimeout(20)
                            if mode=='recv':
                                for pos in range(0,len(data),1021):conn.sendall(data[pos:pos+1021])
                                conn.shutdown(socket.SHUT_WR);result['passed']=True
                            else:
                                h=hashlib.sha256();count=0
                                dec=zlib.decompressobj(31) if mode=='gzip-tcp' else None
                                while True:
                                    chunk=conn.recv(16381)
                                    if not chunk:break
                                    plain=dec.decompress(chunk) if dec else chunk
                                    h.update(plain);count+=len(plain)
                                result['passed']=count==len(data) and h.hexdigest()==wanted and (dec is None or dec.eof and not dec.unused_data)
                    except Exception as e:result['error']=str(e);result['passed']=False
                thread=threading.Thread(target=serve,daemon=True);thread.start()
                target=tmp/'received'
                p=run([driver,mode,address,target] if mode=='recv' else [driver,mode,source,address])
                thread.join(25)
                file_ok=mode!='recv' or target.is_file() and digest(target)==wanted
                record(mode,opt,p.returncode==0 and p.stdout==f'{len(data)}\n'.encode() and result.get('passed',False) and not thread.is_alive() and file_ok,stderr=p.stderr.decode(errors='replace'),server=result)
    report['input_changed']=report['input_sha256']!=inputs()
    report['compiler_changed']=report['compiler_sha256']!=digest(xu)
    report['status']='PASS' if frozen and all(r['passed'] for r in report['results']) and not report['input_changed'] and not report['compiler_changed'] else 'FAIL'
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(report['status']!='PASS')
if __name__=='__main__':main()
