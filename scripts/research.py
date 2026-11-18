"""Read-only upstream research; gh supplies authentication without logging tokens."""
import argparse
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import requests

PROJECTS = {
    'audacity/audacity': 'CMakeLists.txt',
    'Ardour/ardour': 'wscript',
    'LMMS/lmms': 'CMakeLists.txt',
    'musescore/MuseScore': 'CMakeLists.txt',
    'mixxxdj/mixxx': 'CMakeLists.txt',
    'tenacityteam/tenacity': 'CMakeLists.txt',
    'zrythm/zrythm': 'meson.build',
    'surge-synthesizer/surge': 'CMakeLists.txt',
    'Anjok07/ultimatevocalremovergui': 'separate.py',
    'facebookresearch/demucs': 'demucs/apply.py',
    'deezer/spleeter': 'spleeter/separator.py',
    'nomadkaraoke/python-audio-separator': 'audio_separator/separator/separator.py',
    'RVC-Project/Retrieval-based-Voice-Conversion-WebUI': 'infer/modules/vc/modules.py',
    'w-okada/voice-changer': 'server/voice_changer/VoiceChanger.py',
    'xiph/rnnoise': 'src/denoise.c',
    'noise-suppression-for-voice/noise-suppression-for-voice': 'CMakeLists.txt',
    'breakfastquay/rubberband': 'rubberband/RubberBandStretcher.h',
    'rspeyer/soundtouch': 'include/SoundTouch.h',
    'aubio/aubio': 'src/pitch/pitchyin.c',
    'librosa/librosa': 'librosa/core/pitch.py',
    'spotify/basic-pitch': 'basic_pitch/inference.py',
    'csteinmetz1/pyloudnorm': 'pyloudnorm/meter.py',
    'FFmpeg/FFmpeg': 'libavfilter/af_loudnorm.c',
    'PyAV-Org/PyAV': 'av/audio/resampler.py',
    'spatialaudio/python-sounddevice': 'src/sounddevice.py',
    'PortAudio/portaudio': 'include/portaudio.h',
    'juce-framework/JUCE': 'modules/juce_dsp/processors/juce_Oversampling.cpp',
    'steinbergmedia/vst3sdk': 'CMakeLists.txt',
    'microsoft/onnxruntime': 'onnxruntime/python/onnxruntime_inference_collection.py',
    'pyinstaller/pyinstaller': 'PyInstaller/building/build_main.py',
    'obsproject/obs-studio': 'CMakeLists.txt',
    'falkTX/Carla': 'Makefile',
    'DISTRHO/DPF': 'Makefile',
    'muse-sequencer/muse': 'CMakeLists.txt',
    'wwmm/easyeffects': 'meson.build',
    'bmc0/dsp': 'Makefile',
    'Stazed/loopidity': 'CMakeLists.txt',
}


def api(route, raw=False):
    headers = {'Accept': 'application/vnd.github.raw+json' if raw else 'application/vnd.github+json'}
    token = os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    for attempt in range(2):
        try:
            result = requests.get('https://api.github.com/' + route, headers=headers, timeout=(8, 20))
            if result.status_code >= 400:
                return {'error': 'HTTP ' + str(result.status_code)}
            return result.text if raw else result.json()
        except requests.RequestException as exc:
            if attempt:
                return {'error': type(exc).__name__}


def inspect(item):
    repo, source = item
    prefix = 'repos/' + repo
    meta = api(prefix)
    if 'error' in meta:
        return {'repository': repo, **meta}
    sha = api(prefix + '/commits?per_page=1')
    commit = sha[0] if isinstance(sha, list) and sha else {}
    ref = commit.get('sha', meta['default_branch'])
    readme = api(prefix + '/readme', True)
    tree = api(prefix + '/contents?ref=' + ref)
    code = api(prefix + '/contents/' + source + '?ref=' + ref, True)
    issues = api(prefix + '/issues?state=open&per_page=3')
    releases = api(prefix + '/releases?per_page=1')
    return {
        'repository': repo, 'url': meta['html_url'], 'stars': meta['stargazers_count'],
        'forks': meta['forks_count'], 'license': (meta.get('license') or {}).get('spdx_id'),
        'archived': meta['archived'], 'description': meta['description'],
        'language': meta['language'], 'pushed_at': meta['pushed_at'],
        'commit': ref, 'commit_date': commit.get('commit', {}).get('committer', {}).get('date'),
        'root_entries': [v['name'] for v in tree] if isinstance(tree, list) else tree,
        'readme_read': isinstance(readme, str),
        # Store observations, not copies of third-party code or README.
        'readme_lines': len(readme.splitlines()) if isinstance(readme, str) else readme,
        'source_url': meta['html_url'] + '/blob/' + ref + '/' + source,
        'source_read': isinstance(code, str),
        'source_lines': len(code.splitlines()) if isinstance(code, str) else code,
        'source_structure': [line[:160] for line in code.splitlines()
                             if line.startswith(('class ', 'def ', 'project(', 'add_subdirectory('))][:8]
                            if isinstance(code, str) else [],
        'issues': [{'title': x['title'], 'url': x['html_url']} for x in issues]
                  if isinstance(issues, list) else issues,
        'release': [{'tag': x['tag_name'], 'date': x['published_at'], 'url': x['html_url']}
                    for x in releases] if isinstance(releases, list) else releases,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        records = list(pool.map(inspect, PROJECTS.items()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                                      'projects': records}, ensure_ascii=False, indent=2), 'utf-8')
    print(f"Researched {len(records)} repositories; {sum(bool(r.get('source_read')) for r in records)} source reads")
    for r in records:
        print(r['repository'], r.get('license'), 'source=' + str(r.get('source_read')), r.get('error', ''))


if __name__ == '__main__':
    main()
