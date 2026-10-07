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
