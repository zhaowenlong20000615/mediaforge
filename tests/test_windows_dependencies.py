from mediaforge import dependencies


def test_windows_doctor_returns_windows_remedies(monkeypatch):
    monkeypatch.setattr(dependencies.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(dependencies, 'binary', lambda name: None)
    monkeypatch.setattr(dependencies, 'installed', lambda name: False)
    result = {item['id']: item for item in dependencies.checks()}
    for name in ('ffmpeg', 'ffprobe', 'poppler', 'tesseract', 'libreoffice'):
        assert result[name]['available'] is False
        assert 'Windows' in result[name]['install']
        assert 'brew ' not in result[name]['install']
        assert 'apt-get' not in result[name]['install']
    assert 'ffprobe.exe' in result['ffprobe']['install']
    assert 'soffice.exe' in result['libreoffice']['install']


def test_windows_font_discovery_preserves_explicit_override(monkeypatch, tmp_path):
    monkeypatch.setattr(dependencies.platform, 'system', lambda: 'Windows')
    monkeypatch.setenv('WINDIR', str(tmp_path))
    fonts = tmp_path / 'Fonts'
    fonts.mkdir()
    default = fonts / 'msyh.ttc'
    default.write_bytes(b'font-path-fixture')
    monkeypatch.delenv('MEDIAFORGE_FONT', raising=False)
    assert dependencies.font_path() == str(default)
    chosen = tmp_path / 'chosen.ttf'
    chosen.write_bytes(b'font-path-fixture')
    monkeypatch.setenv('MEDIAFORGE_FONT', str(chosen))
    assert dependencies.font_path() == str(chosen)


def test_unknown_platform_does_not_recommend_macos_package_manager(monkeypatch):
    monkeypatch.setattr(dependencies.platform, 'system', lambda: 'FreeBSD')
    assert 'brew ' not in dependencies.install_hint('ffmpeg')
    assert 'ffmpeg' in dependencies.install_hint('ffmpeg')
