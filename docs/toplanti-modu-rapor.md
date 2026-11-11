# Kâtip: toplantı modu raporu (10–11 Kasım 2026)

## Ne yapıldı
- **Program adı Kâtip oldu.** `Katip.exe`, `Katip.zip`, `Katip-NVIDIA.zip`. Veriler `%APPDATA%\Katip`'te; eski `%APPDATA%\MeetTranscriber` klasörü ilk açılışta **kopyalanır**, eskisine dokunulmaz.
- **Toplantı modu.** Yükleme alanındaki anahtar açıksa kayıt yazıya dökülür dökülmez analiz arkada başlar. Eski kayıtlarda **Analiz** sekmesindeki "Analiz et" düğmesi aynı işi yapar.
- **Analiz içeriği:** toplantı puanı (karar, odak, tekrar, söz dengesi), özet, zamanlı konu başlıkları, kararlar, görevler (kim, ne, ne zamana), cevapsız sorular, kişi kartları (konuşma payı, söz sayısı, kelime, soru + katkısı + kazanımı). Her madde satıra bağlı: tıklayınca metne gider ve çalar.
- **İsim bulma:** kayıtlı ses > kural ("ben Deniz", "Burak sen…") ve model aynı şeyi söylüyorsa otomatik > tek kaynak varsa "Burak olabilir?" önerisi. Model, kayıtta hiç geçmeyen bir adı öneremez.
- **Dışa aktarma:** analiz Word / Markdown / TXT / JSON olarak kaydedilir.
- **Sistem sayfası:** "Analiz modeli" kartı (model listesi, uygunluk, indirme, seçim).
- **Tamamen yerel:** llama.cpp (Vulkan ya da işlemci) alt süreç olarak çalışır. Ollama yok, sunucu yok, açık port yok (paketlenmiş exe'de doğrulandı).

## Kim ne yaptı
| İş | Yapan |
|---|---|
| LLM motoru, model kataloğu ve indirme | Sonnet ajanı |
| Analiz hattı (sayılar, notlar, birleştirme, devam etme) | Sonnet ajanı |
| LLM ile isim bulma | Sonnet ajanı |
| Analiz sekmesi, toplantı modu anahtarı, Sistem kartı | EVREN (deepseek-v4.1-flash) |
| Kâtip'e yeniden adlandırma ve veri taşıma | EVREN |
| Analizi dışa aktarma, README | EVREN |
| Kurgusal test toplantısı (cevap anahtarlı) | EVREN |
| Sözleşme, inceleme, birleştirme, ölçümler, hata düzeltmeleri, derleme | Claude (orkestra) |

EVREN'e yalnızca proje kodu ve kurgusal metin gitti; gerçek kayıtlar gitmedi.

## Model ölçümleri
Test: 3 kişilik, 10 dakikalık **kurgusal** Türkçe toplantı (`tests/data/meeting_tr.txt`, 76 satır). Cevap anahtarı: 4 karar, 5 görev, 2 cevapsız soru, isimler Deniz / Burak / Elif. Bilgisayar: RTX 1000 Ada 6 GB, 22 çekirdek. Hepsi 4-bit sıkıştırılmış GGUF.

| Model | İndirme | Bu bilgisayarda | Süre | Karar | Görev | Not |
|---|---|---|---|---|---|---|
| Gemma 3 4B | 2,5 GB | ekran kartı | 53–80 sn | 4/4 (+2–3 fazla) | 5/5, tarih ve satır kayık | Türkçesi akıcı ama koşudan koşuya değişiyor |
| **Qwen3.5 4B** | 2,7 GB | ekran kartı | 58–76 sn | 3/4 | **5/5, kişi + tarih + satır doğru** (5 koşunun 5'inde) | en tutarlı küçük model |
| Gemma 4 E4B | 5,0 GB | işlemci (karta sığmıyor) | 195 sn | **4/4 + 2 doğru ek** | 8, bir kısmı tekrar | en iyi üslup; Elif/Burak adlarını ters verdi |
| Qwen3.5 9B | 5,7 GB | işlemci (karta sığmıyor) | 372 sn | 5 karar, hepsi doğru | 6, tarihler doğru | 4B'ye göre belirgin üstünlük yok, çok daha yavaş |
| Gemma 4 12B | 7,0 GB | işlemci | GEMMA12_SURE | GEMMA12_KARAR | GEMMA12_GOREV | GEMMA12_NOT |

Ek ölçümler (Qwen3.5 4B):
- 80 dakikalık metin: ekran kartında **4 dakika** (ses dakikası başına ~3 sn).
- Yalnız işlemci: 10 dakikalık toplantı tek çağrıda ~110 sn (ekran kartının ~2,5 katı).
- Gerçek ses dosyasıyla tam akış (12 dk): yazıya dökme 48 sn + analiz 41 sn.

### Seçilen varsayılanlar
- **Küçük (varsayılan): Qwen3.5 4B.** 4 GB ve üstü kartlara sığar, görev ve isimlerde en tutarlısı.
- **Büyük (10 GB+ ekran belleği): BUYUK_VARSAYILAN.**
- Sistem sayfasından istenen model elle seçilebilir; karta sığmayan model işlemcide çalışır ("sınırda" etiketi).

## Ölçüm sırasında bulunup düzeltilenler
1. Küçük model son adımda karar/görev listelerini kopyalarken boş bırakıyordu → listeler bölüm notlarından doğrudan alınıyor; model son adımda yalnızca özet, kişi kartları ve puanı yazıyor.
2. Uzun kayıtta isim adımı aynı adı tekrarlayıp çıktıyı taşırıyordu → tüm listelere üst sınır kondu.
3. "Cevapsız sorular" çok gürültülüydü (7 soru, çoğu cevaplanmış) → her aday soru, ardından gelen satırlarla birlikte ayrı bir kısa çağrıda doğrulanıyor.
4. Model bazen talimat cümlesini cevap diye geri yazıyordu → talimat metniyle aynı olan çıktılar atılıyor; boş kalan kişi kartı bölüm notlarından dolduruluyor.
5. İngilizce test kaydında model, talimattaki örnek adı ("Elif") konuşmacıya verdi → kayıtta geçmeyen ad kabul edilmiyor.
6. İşlemci modunda motor yine de ekran kartına iş veriyordu → kapatıldı.
7. Deneme paketi 11 GB çıktı (indirdiğim dil modelleri pakete giriyordu) → paket yalnızca konuşmacı modellerini içeriyor; dil modeli uygulamadan indiriliyor.

## Bilinen sınırlar (dürüstçe)
- **4B model hata yapar.** Görevler ve isimler güvenilir çıktı; ama "cevapsız sorular" koşudan koşuya değişiyor (0–3 madde), kişi "kazanımı" metinlerinde ara sıra uydurma ayrıntı oldu (ör. "2.3 sürümü"), 4 karardan biri ("offline mod 2.5'e") çoğu koşuda atlandı.
- **Toplantı puanı ayırt edici değil:** model hep 85–98 veriyor (konu dışı sohbet olsa bile). Yalnız "denge" kesin sayıdan geliyor. Puanı göstergeden çok süs olarak görmek gerek; istenirse sayılara dayalı hâle getirilebilir.
- Ölçüm tek bir kurgusal toplantıyla yapıldı; gerçek toplantılarda (üst üste konuşma, yazım hataları) sonuç daha kötü olabilir.
- Büyük modeller bu bilgisayarda yalnızca işlemcide denendi (kart 6 GB). 10 GB+ kartta hızları ölçülmedi.
- Gerçek AMD / Intel Arc kartta hâlâ deneme yok.
- İlk açılış sihirbazı ile Analiz modelinin uygulama içinden indirilmesi baştan sona denenmedi (indirme kodu birim testli; hat ~1,3 MB/sn olduğu için 2,7 GB ≈ 35 dk).

## Senin yapman gerekenler
1. `dist\Katip.zip` (ya da NVIDIA için `Katip-NVIDIA.zip`) → aç, `Katip.exe`.
2. **Sistem → Analiz modeli → Qwen 3.5 4B → İndir** (bir kez, 2,7 GB). Geliştirme bilgisayarında modeller zaten `models\llm\` klasöründe; tekrar indirmemek için `Qwen3.5-4B-Q4_K_M.gguf` dosyasını `%APPDATA%\Katip\models\llm\` içine kopyalayabilirsin.
3. Yükleme alanında **Toplantı modu**'nu aç ya da eski bir kayıtta **Analiz → Analiz et**.
4. GitHub'a hiçbir şey gönderilmedi; tüm değişiklikler yerel commit'lerde.

`models\llm\` klasöründe ölçüm için inen 5 model (~23 GB) duruyor; kullanmayacaklarını silebilirsin.
