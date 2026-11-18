#!/usr/bin/env bash
# Run with MSYS2 bash from the repository root. Install the UCRT64 GCC toolchain first.
set -euo pipefail
export PATH=/ucrt64/bin:/usr/bin:$PATH
stage="$PWD/build/codec-src"
out="$PWD/build/codecs"
mkdir -p "$stage" "$out"
fetch() {
    if [[ ! -f "$stage/$1" ]] || ! (cd "$stage" && echo "$2  $1" | sha256sum -c --status); then
        curl -fLsS --retry 3 "$3" -o "$stage/$1"
    fi
    (cd "$stage" && echo "$2  $1" | sha256sum -c)
}
fetch source.txz 464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz
fetch make.pkg.tar.zst af0bdba17f06fe037f0194069adaa31a8fe45f1a11381501896aea1fae37bd5d https://repo.msys2.org/msys/x86_64/make-4.4.1-3-x86_64.pkg.tar.zst
fetch lame.pkg.tar.zst 6bc4bf7d2f39a941a695b228818a8c846a53c43c20117e0707e08977b0dd0da9 https://repo.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-lame-3.100-3-any.pkg.tar.zst
# FFmpeg's configure/make toolchain requires paths without spaces.
work=$(mktemp -d /tmp/voxmaster-codecs.XXXXXXXX)
cd "$work"
tar -xf "$stage/make.pkg.tar.zst"
tar -xf "$stage/lame.pkg.tar.zst"
tar -xf "$stage/source.txz"
export PATH="$work/ucrt64/bin:$work/usr/bin:$PATH"
# cmdline arguments for the native Windows compiler need Windows paths.
prefix=$(cygpath -m "$work/ucrt64")
cd ffmpeg-8.1.2
./configure --prefix="$work/ffbuild" --target-os=mingw32 --arch=x86_64 --enable-shared --disable-static     --disable-autodetect --disable-debug --disable-doc --disable-programs --disable-network --disable-x86asm     --disable-everything --disable-iconv --enable-libmp3lame --extra-cflags="-I$prefix/include"     --extra-ldflags="-L$prefix/lib" --enable-protocol=file,pipe     --enable-demuxer=wav,mp3,flac,mov,aac,ogg,aiff --enable-muxer=wav,mp3,flac,ipod,adts,ogg,aiff     --enable-encoder=pcm_s16le,pcm_s24le,pcm_f32le,pcm_s16be,flac,aac,libmp3lame     --enable-decoder='pcm_*,mp3*,flac,aac*,alac,vorbis,opus'     --enable-parser=mpegaudio,aac,aac_latm,flac,opus,vorbis --enable-bsf=aac_adtstoasc     --enable-filter=abuffer,abuffersink,aformat,aresample,anull,pan
make -j8
make install
cp "$work"/ffbuild/bin/*.dll "$out/"
cp "$work"/ucrt64/bin/libmp3lame-0.dll "$out/"
cp /ucrt64/bin/libwinpthread-1.dll "$out/"
cp /ucrt64/share/licenses/libwinpthread/COPYING "$out/COPYING.winpthreads"
cp COPYING.LGPLv2.1 "$out/COPYING.FFmpeg"
cp "$stage/source.txz" "$out/ffmpeg-8.1.2.tar.xz"
cp ffbuild/config.log "$work/ffmpeg-config.log"
echo "FFmpeg 8.1.2 libraries ready in $out. Scratch build in $work."
