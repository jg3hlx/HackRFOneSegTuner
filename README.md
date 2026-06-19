# HackRF One-Seg Tuner

HackRF One で日本の地上デジタルテレビ（ISDB-T）のワンセグ放送をリアルタイム受信・表示するツール群。

## セットアップ

```bash
git clone --recursive git@github.com:Iwancof/HackRFOneSegTuner.git
cd HackRFOneSegTuner

# gr-isdbt ビルド
cd gr-isdbt
mkdir build && cd build
cmake -DCMAKE_INSTALL_PREFIX=$(gnuradio-config-info --prefix) ..
make -j$(nproc)
sudo make install
sudo ldconfig
cd ../..
```

### 依存パッケージ (Arch Linux)

```bash
sudo pacman -S gnuradio gr-osmosdr hackrf ffmpeg python-numpy
```

## 使い方

```bash
# ch23（テレビ東京）をリアルタイム受信
python3 live_oneseg.py 23

# 自動校正モード（初回推奨）
python3 live_oneseg.py 23 --calibrate

# サブキャリアオフセットを直接指定
python3 live_oneseg.py 23 --sc 11

# IQデータをキャプチャして保存
python3 capture_iq.py 23 -o ch23.cf32 --duration 30

# 保存済みIQからオフライン復号
python3 offline_test2.py ch23.cf32 --full-chain --freq-offset -10913 -o out.ts

# 全チャンネルスキャン
python3 fast_scan.py
```

## gr-isdbt パッチ内容

[tildearrow/gr-isdbt](https://github.com/tildearrow/gr-isdbt) からの fork に以下の修正を適用済み:

- **VOLK パディング**: SIMD バッファオーバーラン防止
- **周波数オフセット探索範囲拡大** (±10 → ±30): HackRF 等の低コスト SDR 対応
- **整数周波数オフセットの二重適用修正**: データキャリア復号の根本バグ修正
- **同期ロス判定閾値の緩和** (0.75 → 2.0): リセットループ防止

## 構成

| ファイル | 説明 |
|---|---|
| `live_oneseg.py` | リアルタイム受信 (HackRF → ffplay) |
| `offline_test2.py` | オフライン IQ 復号 |
| `capture_iq.py` | IQ キャプチャ |
| `fast_scan.py` | 全チャンネル TMCC スキャン |
| `PIPELINE.md` | 信号処理パイプラインの詳細解説 |
| `gr-isdbt/` | パッチ済み ISDB-T デコーダ (submodule) |
| `dev/` | 開発中の実験スクリプト |
