#!/usr/bin/env python3
"""Build the real Xu LCD wireless demo. Credentials are private build input."""
from pathlib import Path
import argparse,json,shutil,subprocess,os,struct,re

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--xu-root',type=Path,required=True)
    ap.add_argument('--network-config',type=Path);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();root=a.xu_root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
    demo=Path(__file__).resolve().parent
    env=dict(os.environ,XU_ROOT=str(root),XU_STDLIB_ROOT=str(root/'src'),XUPATH='')
    # This IRAM closure contains scalar IRQ/flash workers. It imports neither
    # the IROM Wi-Fi facade nor the heap-owning SMP AES adapter.
    std=out/'iram-stdlib';std.mkdir(exist_ok=True)
    for p in (root/'src').iterdir():
        q=std/p.name
        if not q.exists() and not q.is_symlink():q.symlink_to(p,target_is_directory=p.is_dir())
    for rel in ['embedded','embedded/chips','embedded/chips/esp32']:
        q=std/rel
        if q.is_symlink():q.unlink();q.mkdir()
        for p in (root/'src'/rel).iterdir():
            if rel=='embedded/chips/esp32' and p.name in ['wifi.xu','wifi_phy.xu','smp_aes.xu']:continue
            d=q/p.name
            if not d.exists() and not d.is_symlink():d.symlink_to(p,target_is_directory=p.is_dir())
    native=out/'native_radio.elf'
    subprocess.run([str(root/'bin/xu'),'build',str(demo/'native_radio.xu'),'--target','xtensa-esp32-none','--board','esp32-iram','-o',str(native)],env=dict(env,XU_STDLIB_ROOT=str(std)),check=True)
    nm=os.environ.get('XTENSA_NM') or shutil.which('xtensa-esp32-elf-nm')
    if not nm:
        candidates=sorted((Path.home()/'.espressif/tools/xtensa-esp32-elf').glob('*/xtensa-esp32-elf/bin/xtensa-esp32-elf-nm'))
        if not candidates:raise RuntimeError('set XTENSA_NM or install the Xtensa binutils')
        nm=str(candidates[-1])
    syms={p[2]:int(p[0],16) for l in subprocess.check_output([str(nm),str(native)],text=True).splitlines() if len(p:=l.split())==3}
    b=bytearray(native.read_bytes());off=struct.unpack_from('<I',b,28)[0];ph=struct.unpack_from('<8I',b,off)
    if ph[0]!=1 or ph[2]!=0x40080000 or ph[2]+ph[5]>0x400A0000:raise RuntimeError('IRAM closure outside radio profile')
    struct.pack_into('<H',b,44,1);code=out/'native_radio_codeonly.elf';code.write_bytes(b)
    source=demo/'ble_transport.xu';s=source.read_text()
    # Patch from the recorded source map, so repeated builds are deterministic.
    mapping=json.loads((demo/'native_bindings.json').read_text())
    replacements={}
    for symbol,address in mapping.items():
        if symbol not in syms:raise RuntimeError('missing scalar callback '+symbol)
        if not re.search(r'\b'+re.escape(address)+r'\b',s,re.I):raise RuntimeError('missing callback placeholder '+symbol)
        replacements[address.lower()]=hex(syms[symbol])
    pattern=r'\b(?:'+ '|'.join(re.escape(k) for k in replacements)+r')\b'
    s=re.sub(pattern,lambda m:replacements[m.group(0).lower()],s,flags=re.I)
    (out/'ble_transport.xu').write_text(s)
    app=(demo/'main.xu').read_text()
    if a.network_config:
        n=json.loads(a.network_config.read_text())
        for key in ['ssid','password']:
            if not isinstance(n.get(key),str):raise RuntimeError('network config requires ssid/password strings')
            app=app.replace('fn configured_'+key+'() string { << "" }','fn configured_'+key+'() string { << '+json.dumps(n[key],ensure_ascii=False)+' }')
    (out/'main_private.xu').write_text(app);(out/'main_private.xu').chmod(0o600)
    names=['panel','font','touch','ui','mode','ble_app']
    for name in names:shutil.copyfile(demo/(name+'.xu'),out/(name+'.xu'))
    sources=[out/'main_private.xu',out/'ble_transport.xu']+[out/(n+'.xu') for n in names]
    elf=out/'wireless_status.elf';image=out/'wireless_status.bin'
    subprocess.run([str(root/'bin/xu'),'build',*[str(p) for p in sources],'--target','xtensa-esp32-none','-o',str(elf)],env=env,check=True)
    subprocess.run(['python3',str(root/'scripts/esp32_image.py'),'pack-multi',str(image),str(elf),str(code),'--radio'],check=True)
    subprocess.run(['python3',str(root/'scripts/esp32_image.py'),'verify',str(image)],check=True)
    if image.stat().st_size>0x300000:raise RuntimeError('image exceeds the factory partition and would overwrite bond storage')
    for p in [native,code,elf,image]:p.chmod(0o600)
    print('Xu wireless LCD image ready:',image)

if __name__=='__main__':main()
