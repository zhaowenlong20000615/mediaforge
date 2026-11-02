"""A cached dependency update must refuse the wrong deployed source before pip."""
import hashlib
import importlib.util
import json
import tarfile
from pathlib import Path
import pytest


def test_wrong_dependency_cache_cannot_install_or_switch(tmp_path,monkeypatch):
    source=Path(__file__).parents[1]/'deploy/remote.py'
    spec=importlib.util.spec_from_file_location('mediaforge_release_guard',source)
    remote=importlib.util.module_from_spec(spec);spec.loader.exec_module(remote)
    base=tmp_path/'mediaforge';incoming=base/'incoming';incoming.mkdir(parents=True)
    old=base/'releases/previous';(old/'wheels').mkdir(parents=True)
    (old/'release.json').write_text(json.dumps({'version':'0.2.3','git_commit':'a'*40}))
    current=base/'current';current.symlink_to(old)
    artifact=incoming/'mediaforge-0.2.4-fixture.tar.gz'
    with tarfile.open(artifact,'w:gz'):pass
    digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata={'project_id':'local.mediaforge','version':'0.2.4','git_commit':'c'*40,'artifact_sha256':digest,'dependency_cache_commit':'b'*40}
    Path(str(artifact)+'.release.json').write_text(json.dumps(metadata))
    Path(str(artifact)+'.sha256').write_text(digest+'  '+artifact.name+'\n')
    monkeypatch.setattr(remote,'BASE',base);monkeypatch.setattr(remote,'CURRENT',current)
    def reject_command(*args,**kwargs):pytest.fail('Dependency mismatch must be rejected before installation')
    monkeypatch.setattr(remote,'command',reject_command)
    with pytest.raises(RuntimeError,match='declared dependency cache'):remote.activate(artifact.name)
    assert current.resolve()==old and not (base/'deployment.json').exists()


def test_retention_protects_runtime_graph_and_revalidates_content(tmp_path,monkeypatch):
    source=Path(__file__).parents[1]/'deploy/retention.py';spec=importlib.util.spec_from_file_location('mf_retention',source);r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
    base=tmp_path/'mediaforge';(base/'access').mkdir(parents=True);proc=tmp_path/'proc';proc.mkdir();monkeypatch.setattr(r,'PROC_ROOT',proc)
    def release(root,name):
        p=root/'releases'/name;p.mkdir(parents=True)
        (p/'release.json').write_text(json.dumps({'project_id':'local.mediaforge','version':'0.2.7','artifact_sha256':name}))
        (p/'deployment.json').write_text(json.dumps({'project_id':'local.mediaforge'}));return p
    old=release(base,'old');current=release(base,'current');previous=release(base,'previous');unused=release(base,'unused')
    (old/'.venv/bin').mkdir(parents=True);(old/'.venv/bin/python').write_text('runtime')
    (current/'.venv/bin').mkdir(parents=True);(current/'.venv/bin/cli').write_text('#!'+str(old/'.venv/bin/python')+'\n')
    (base/'current').symlink_to(current);(base/'previous.json').write_text(json.dumps({'release':str(previous)}))
    access=base/'access';ac=release(access,'current');ap=release(access,'previous');au=release(access,'unused')
    (ac/'deployment.json').write_text(json.dumps({'project_id':'local.mediaforge','previous':str(ap)}));(access/'current').symlink_to(ac)
    (base/'incoming').mkdir();(access/'incoming').mkdir()
    plan=r.plan(base);paths={x['path'] for x in plan['candidates']}
    assert str(old) in plan['kept'] and str(current) in plan['kept'] and str(previous) in plan['kept']
    assert paths=={str(unused),str(au)}
    # Changed bytes invalidate the fingerprint, even when length is unchanged.
    p=unused/'payload';p.write_text('abc');a=r.snapshot(unused)[0];p.write_text('abd');assert r.snapshot(unused)[0]!=a
    applied=r.retain(base,True);assert len(applied['deleted'])==2
    assert all(x.exists() for x in [current,previous,old,ac,ap])
    assert not r.retain(base,True)['deleted']
