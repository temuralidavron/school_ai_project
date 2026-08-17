# GStreamer va DeepStream — qisqacha farqi (kod bilan)

> Maqsad: bir qarashda tushunish. Bu bizning `deepstream_v3/pipeline/main.py`ning
> soddalashtirilgan skeleti — har qator kimniki ekani izohlangan.

## Bir gapda

- **GStreamer** = konveyer lentasi — kadrlarni uzatadi, o'zi hech narsani tanimaydi. Bepul, hamma joyda bor.
- **DeepStream** = shu lentaga o'rnatiladigan NVIDIA robotlari — og'ir ishni (yuz topish, kuzatish) **GPU'da** qiladi. Faqat Linux.
- Ular raqobatchi EMAS — biri ikkinchisining ustiga quriladi. Biz ikkalasini birga ishlatamiz.
- Tezlik farqi (o'zimiz o'lchaganmiz): eski CPU yo'l **14 fps** → DeepStream **1200+ fps** → 1 GPU = 20 kamera.

## Jarayon — bitta kadrning yo'li (8 qadam)

```
[1] filesrc/rtsp  ──► [2] h264parse ──► [3] nvv4l2decoder ──► [4] nvstreammux
    videoni o'qish      kadr chegara       GPU'da ochish        20 kamera = 1 batch
    (GStreamer)         (GStreamer)        (DeepStream)         (DeepStream)
                                                                      │
        ┌─────────────────────────────────────────────────────────────┘
        ▼
[5] nvinfer ──► [6] nvtracker ──► [7] probe ──────► [8] bizning kod
    yuz topish      ID berish        natijani o'qish     ArcFace → 512 kod
    SCRFD           NvDCF            (GStreamer)         → Kafka → davomat
    (DeepStream)    (DeepStream)                         (Python)
```

| Qadamlar | Kim | Qayerda |
|---|---|---|
| 1, 2, 7 | **GStreamer** — quvur karkasi | CPU (yengil) |
| 3, 4, 5, 6 | **DeepStream** — NVIDIA plaginlari | **GPU** (og'ir ish) |
| 8 | **Bizning kod** — qaror, davomat | Python + ArcFace |

Bir jumlada: *kadr GStreamer quvuriga kiradi, DeepStream uni GPU'da ochib yuzni topadi
va kuzatadi, keyin GStreamer'ning "quloq"i (probe) orqali natija bizning kodga o'tadi.*

## Kod (izohli skelet)

```python
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst          # GSTREAMER — butun API shu kutubxonadan

Gst.init(None)                          # GSTREAMER — konveyerni yoqish
pipeline = Gst.Pipeline()               # GSTREAMER — bo'sh quvur

# ── ELEMENTLAR (yasovchi — GStreamer, "nv"li detallar — NVIDIA/DeepStream)
src    = Gst.ElementFactory.make("filesrc")        # GSTREAMER — videoni o'qiydi
parse  = Gst.ElementFactory.make("h264parse")      # GSTREAMER — kodek sarhadlari
dec    = Gst.ElementFactory.make("nvv4l2decoder")  # DEEPSTREAM — GPU'da ochadi (NVDEC)
mux    = Gst.ElementFactory.make("nvstreammux")    # DEEPSTREAM — 20 kamerani 1 batch
infer  = Gst.ElementFactory.make("nvinfer")        # DEEPSTREAM — YUZ TOPISH (TensorRT)
track  = Gst.ElementFactory.make("nvtracker")      # DEEPSTREAM — bolani kuzatish (ID)
sink   = Gst.ElementFactory.make("fakesink")       # GSTREAMER — quvur oxiri

src.set_property("location", "sinf.mp4")           # GSTREAMER — sozlash usuli
infer.set_property("config-file-path", "det.txt")  # DEEPSTREAM — qaysi model

# ── ULASH (quvurni yig'ish) — bu mexanika 100% GStreamer
for el in (src, parse, dec, mux, infer, track, sink):
    pipeline.add(el)
src.link(parse); parse.link(dec); dec.link(mux)
mux.link(infer); infer.link(track); track.link(sink)

# ── NATIJANI O'QISH — GStreamer'ning "probe" mexanizmi orqali
#    DeepStream qoldirgan metadata (yuzlar, ID'lar) shu yerda olinadi
def probe(pad, info, _):
    # DEEPSTREAM metadata: har yuzning bbox'i + track ID'si
    # shu yerdan BIZNING KOD ArcFace'ga uzatadi -> 512-son kod -> Kafka -> davomat
    return Gst.PadProbeReturn.OK

track.get_static_pad("src").add_probe(   # GSTREAMER — quvurga "quloq" qo'yish
    Gst.PadProbeType.BUFFER, probe, None)

pipeline.set_state(Gst.State.PLAYING)    # GSTREAMER — konveyerni yurgizish
```

## Xulosa jadval

| Qism | Kimniki | Qayerda ishlaydi |
|---|---|---|
| Quvur karkasi, ulash, probe, yurgizish | GStreamer | CPU (yengil) |
| Decode, batch, yuz topish, kuzatuv (`nv...`) | DeepStream | **GPU** (og'ir ish) |
| Tanish qarori, davomat, SKUD | Bizning Python kod | CPU (yengil) + ArcFace GPU |

Boshliq uchun bir jumla: *"GStreamer — video uzatish poydevori, DeepStream — NVIDIA'ning
shu poydevor ustidagi GPU-tezlashtirgichi. Ikkalasini birga ishlatamiz: 14 fps o'rniga
1200+ fps, bitta videokarta 20 kamera."*
