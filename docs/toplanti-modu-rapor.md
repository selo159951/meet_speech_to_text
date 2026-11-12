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
| **Qwen3.5 4B** | 2,7 GB | ekran kartı | 58–79 sn | 3/4 + 1 doğru ek | **5/5, kişi + tarih + satır doğru** (bütün koşularda) | en tutarlısı; kişi kartları temiz ve kişiye özel |
| Gemma 3 4B | 2,5 GB | ekran kartı | 53–80 sn | **4/4** + 1 doğru ek | 5/5 + 2 fazla (biri yanlış kişiye) | Türkçesi akıcı; "cevapsız sorular" çok gürültülü (8 madde) |
| Gemma 4 E4B | 5,0 GB | işlemci (karta sığmıyor) | 195 sn | 4/4 + 2 doğru ek | 8, bir kısmı tekrar | en iyi üslup; Elif/Burak adlarını ters verdi. Sohbet biçimi olmadan ölçüldü |
| Qwen3.5 9B | 5,7 GB | işlemci (karta sığmıyor) | 332 sn | **4/4** + 1 doğru ek | 5/5 + 1 ek, tarihler doğru | en isabetli sonuç; kişi kartları da en iyisi. Kartta (8 GB+) çok daha hızlı olması beklenir, ölçülemedi |
| Gemma 4 12B | 7,0 GB | işlemci | 13 dk, **başarısız** | – | – | bozuk JSON döndürdü; listeden çıkarıldı |

Önemli not: ölçümlerin ilk turunda motor, modelleri kendi sohbet biçimleri olmadan çalıştırıyordu. Bunu fark edip Qwen (ChatML) ve Gemma 3 için düzelttim; yukarıdaki Qwen3.5 4B ve Gemma 3 4B satırları düzeltmeden **sonraki** sonuçlardır. Gemma 4'ün biçiminden emin olmadığım için o modeller düz tamamlama olarak çalışıyor; bu yüzden Gemma 4 satırları modele haksızlık ediyor olabilir.

Ek ölçümler (Qwen3.5 4B):
- 80 dakikalık metin: ekran kartında **4 dakika** (ses dakikası başına ~3 sn).
- Yalnız işlemci: 10 dakikalık toplantı tek çağrıda ~110 sn (ekran kartının ~2,5 katı).
- Gerçek ses dosyasıyla tam akış (12 dk): yazıya dökme 48 sn + analiz 41 sn.

### Seçilen varsayılanlar
- **Küçük (varsayılan): Qwen3.5 4B.** 4 GB ve üstü kartlara sığar, görev ve isimlerde en tutarlısı.
- **Büyük (8 GB+ ekran belleği): Qwen3.5 9B.** Planda 10 GB+ için 12B sınıfı düşünülmüştü; Gemma 4 12B ölçümde bozuk çıktı verdiği için büyük seçenek 9B oldu.
- Sistem sayfasından istenen model elle seçilebilir; karta sığmayan model işlemcide çalışır ("sınırda" etiketi).

## Ölçüm sırasında bulunup düzeltilenler
1. Küçük model son adımda karar/görev listelerini kopyalarken boş bırakıyordu → listeler bölüm notlarından doğrudan alınıyor; model son adımda yalnızca özet, kişi kartları ve puanı yazıyor.
2. Uzun kayıtta isim adımı aynı adı tekrarlayıp çıktıyı taşırıyordu → tüm listelere üst sınır kondu.
3. "Cevapsız sorular" çok gürültülüydü (7 soru, çoğu cevaplanmış) → her aday soru, ardından gelen satırlarla birlikte ayrı bir kısa çağrıda doğrulanıyor.
4. Model bazen talimat cümlesini cevap diye geri yazıyordu → talimat metniyle aynı olan çıktılar atılıyor; boş kalan kişi kartı bölüm notlarından dolduruluyor.
5. İngilizce test kaydında model, talimattaki örnek adı ("Elif") konuşmacıya verdi → kayıtta geçmeyen ad kabul edilmiyor.
6. İşlemci modunda motor yine de ekran kartına iş veriyordu → kapatıldı.
7. Motor, modelleri sohbet biçimi olmadan çalıştırıyordu (talimatı geri yazma ve uydurma ayrıntıların asıl nedeni) → Qwen ve Gemma 3 için biçim elle yazılıyor; kalite belirgin arttı.
8. Deneme paketi 11 GB çıktı (indirdiğim dil modelleri pakete giriyordu) → paket yalnızca konuşmacı modellerini içeriyor; dil modeli uygulamadan indiriliyor.

## Bilinen sınırlar (dürüstçe)
- **4B model hata yapar.** Görevler ve isimler güvenilir çıktı; ama "cevapsız sorular" zayıf: son sürümde Qwen iki gerçek cevapsız soruyu da kaçırdı (liste boş), Gemma 3 ise 8 madde yazdı. 4 karardan biri ("offline mod 2.5'e") Qwen'de çoğu koşuda atlandı.
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


## Kalite turu (11 Kasım, "hatasız ve kaliteli analiz")
Gerçek kayıtlarındaki bir analizde (12 saniyelik deneme, işlemcide 9B) 146 sn sürmüş ve model olmayan şeyler yazmıştı. Yapılanlar:

- **Ekran kartı:** 7 GB'lık 9B model 6 GB karta sığmadığı için tamamen işlemcide çalışıyordu. Artık sığmayan modelin bir kısmı kartta çalışır; analizden önce Whisper kart belleğinden bırakılır. Senin klasörüne Qwen 4B kopyalandı: tamamen karta sığar, otomatik o seçilir (paketli exe'de doğrulandı: Vulkan, 3,8 GB kart belleği, 88 sn).
- **Hata dayanıklılığı:** model çıktısı bozuksa 3 kez dener; kartta hata olursa işlemcide yeniden dener; bir çağrı en fazla 25 dk bekler. Bir bölüm ya da özet yazılamazsa analiz çökmez: bulunanlar gösterilir, uyarı çıkar. Hiçbiri olmazsa net hata mesajı verir.
- **Kararlar:** her bölüm için ayrı, tek amaçlı bir "yalnızca kararlar" taraması eklendi. Kurgusal toplantıda 4 önemli kararın 4'ü de bulunuyor (eskiden çoğu koşuda 2-3). Görev gibi duran "kararlar" ve aynı satırdaki tekrarlar ayıklanır.
- **Uydurmaya karşı:** kayıtta hiç geçmeyen sürüm/miktar/yıl içeren cümleler ve maddeler atılır ("2.3'e gitti" gibi). Alıntılanan satır numarası birkaç satır kaymışsa, maddeyi gerçekten söyleyen satıra oturtulur.
- **Dürüst puan:** model her toplantıya 85-98 veriyordu. Artık puan dökümden hesaplanıyor: karar sayısı (süreye göre), görev netliği (sorumlu + tarih), cevaplanan sorular, tekrarsızlık, konuşma dengesi. Değerlendirilecek şey yoksa o çubuk gösterilmez. Model yalnızca yorum ve önerileri yazar.
- **Çok kısa kayıtlar** (60 sn altı ya da 6 satırdan az): puan ve kişi değerlendirmesi verilmez, "kayıt çok kısa" notu çıkar; böylece küçük örnekler hakkında uydurma yorum yazılmaz.

Sonuç (Qwen3.5 4B, kurgusal toplantı, 3 koşu, Vulkan, 67-90 sn): isim 3/3, görev 6/6 (kişi, tarih, satır doğru), önemli karar 4/4, uydurma sayı yok. Hâlâ geçerli sınırlar: "cevapsız sorular" koşudan koşuya değişir; gerçek toplantılarla (üst üste konuşma, yazı hataları) denenmedi.

## Konuşmacı ayırma ve isimlendirme turu (11 Kasım)
Gerçek bir kayıt (17 dk, ~20 kişilik öğretmen-öğrenci toplantısı) kopyası üzerinde denendi:
- **3 konuşmacı sınırı kaldırıldı.** Eski kod 3'ten fazla ses bulunca zorla 3'e indiriyordu; 15 kişi tek konuşmacı oldu. Artık gerçekten çok konuşan kişiler (en fazla 20) ayrı kalıyor, birkaç saniyelik yan sesler en yakın gerçek konuşmacıya katılıyor. Sonuç: 3 → 19 konuşmacı. 22 tanıtım satırının 17'si ayrı konuşmacıya düştü (tavan ~19-20; bazı öğretmenler birden çok kez konuşuyor).
- **Daha iyi ses modeli arandı, bulunamadı.** Resmî sherpa-onnx sürümlerinden 5 aday indirildi (WeSpeaker ResNet34 ve CAM++, 3D-Speaker CAM++ Çince+İngilizce, 3D-Speaker ERes2Net İngilizce, NeMo TitaNet small) ve 5 eşik değerinde denendi. Kullandığımız model (3D-Speaker ERes2Net, eşik 0,6) hepsinin en iyisiydi (17/22). Model değiştirilmedi.
- **İsim kuralları sıkılaştı:** iki farklı isimle kendini tanıtan ses (birden çok kişi karışmış) isimsiz kalır; model "Elif" gibi bir adı, o cümleyi başkası söylediyse ya da konuşmacı başkasından söz ediyorsa ("Paula'ya geçelim") vermez; okul/yer adları ("Ayla Lisesi") kişi sayılmaz; adın kayıtta gerçekten geçmesi şart; tanıtım/seslenme olmayan adlar yalnızca öneri olur. Büyük harfsiz yazılmış tanıtımlar da ("my name is melisa") bulunur.
- Sonuç: aynı kayıtta 19 konuşmacıdan 17'si doğru adla, 2'si isimsiz ("Konuşmacı 3", "Konuşmacı 19"); yanlış ad kalmadı. Bilinen zayıflık: kendini tanıtmayan kişiler isimsiz kalır; transkriptte Türkçe özel adlar bozuk yazılabilir (okul adları gibi).

## Türkçe konuşma tanıma modelleri karşılaştırması (11 Kasım)
Hugging Face'te faster-whisper formatında Türkçe ince ayarlı modeller var. İkisi denendi (aynı 12 kısa ses: 5 temiz yapay ses, bunların telefon bandı + gürültülü hâlleri, karışık TR+EN cümle ve senin gerçek sesin; ölçü: kelime hata oranı, düşük iyi):

| Model | Temiz | Gürültülü | Gerçek ses (13 sn) | Hız |
|---|---|---|---|---|
| **large-v3-turbo (şu anki)** | **%1,6** | %4,0 | **%3,3** | 13 sn |
| large-v3 Türkçe ince ayar (turkmedstt tabanlı, int8) | %3,0 | **%3,3** | %6,7 | 32 sn (2,5 kat yavaş) |
| large-v3-turbo Türkçe ince ayar (selimc tabanlı) | %6,7 | %4,9 | %16,7 | 12 sn |

Sonuç: şu anki model değiştirilmedi. Örnek küçük ve çoğu yapay ses; gerçek toplantılarla fark değişebilir. Bir "Türkçe uzman" model denemek istenirse en iyi aday large-v3 ince ayarı; gürültüde biraz iyi, ama yavaş.

## Kişileri öğrenme ve kısa araya girmeler (11 Kasım)
Tasarım EVREN'e (glm-5.3) danışılarak çıkarıldı, kodu EVREN (deepseek) inceledi; önerilerinin bir kısmı kendi ölçümlerimle değiştirildi.

**Ölçüm (20 kişilik gerçek kayıt, 15 adı bilinen kişi, aynı kişinin ses izi iki yarıdan):** aynı kişi 0,81-0,91 benzer (ortalama 0,91); farklı kişiler ortalama 0,28, en fazla 0,66 (%99'u 0,62 altında). En yakın kişiyi bulma 15/15. Eski eşik 0,50 farklı kişi çiftlerinin %8,6'sını yanlışlıkla eşleştirirdi.

- **Eşikler:** otomatik isim 0,65 ve ikinci en yakın kişiden en az 0,08 önde olmalı; 0,50-0,65 arası yalnızca "Selim olabilir?" önerisi. (EVREN 0,70/0,60 önermişti; farklı oturum/mikrofonda aynı kişinin benzerliği düşeceği için biraz gevşek bıraktım, ikinci en yakın kişi kuralı güvenliği sağlıyor.)
- **Kısa cümleler:** her cümle için ses izi çıkarılıp tüm toplantı birden çözülüyor (Viterbi): cümle en çok benzediği sese gider, konuşmacı değiştirmenin bir bedeli vardır, "Thank you." gibi kapanış sözlerinden sonra bu bedel yarıya iner. Moderatörün kısa sözleri eskiden 8/10 doğru konuşmacıya gidiyordu, şimdi 10/10.
- **Bölünmüş konuşmacı birleştirme:** iki konuşmacının ses izi ≥0,72 benzer ve birbirinin en yakını ise (ve her biri ikinciden ≥0,05 öndeyse) tek kişidir. Gerçek kayıtta moderatör öğretmen ile "Greta" kümesi böyle birleşti (0,75; diğer tüm çiftler ≤0,66).
- **Otomatik öğrenme:** kendini tek bir isimle tanıtan, en az 15 sn temiz konuşması olan ve tek sesten oluşan konuşmacı Kişiler'e "otomatik" olarak eklenir. Aynı isimde kişi varsa yalnızca benzeyen ses eklenir (≥0,60); başka isimli birine ≥0,70 benziyorsa öğrenilmez. Otomatik kişi, kullanıcı onaylayana ya da ikinci toplantıda duyulana kadar **yalnızca öneri** yapar. Gerçek kayıtta 1. toplantıda 5 kişi öğrenildi (9 kişi 15 sn'den az konuştuğu için atlandı), aynı kayıt tekrar işlenince 5'i de önerildi (benzerlik ≥0,99) ve ikinci toplantı sayıldı.
- Sınır: kalabalık toplantıda öğrencilerin çoğu 15-30 sn konuşuyor, ses izleri "zayıf" işaretlenir. Aynı kişiyi farklı mikrofon ve odada tanıma oranı gerçek ikinci bir toplantıyla ölçülmedi (yalnızca aynı kayıt).

## Güven işaretleri ve dil seçimi (12 Kasım)
- **"Çeviri" sorunu:** Model çeviri yapmaz; ama dili yanlış tahmin ederse İngilizce konuşmayı Türkçe yazar ("Teşekkürler Ece'den teşekkürler"). Sebep: "Karışık" ayarında her 30 sn pencere kendi başına dil algılıyordu, İngilizce konuşan Türk aksanlı pencereler "Türkçe" çıkıyordu. Artık önce **tüm kaydın** dili 12 pencerede oylanıyor (kayıt %98,7 İngilizce çıktı) ve yazı hep o dilde yapılıyor. "Karışık" mod yalnızca kayıtta gerçekten konuşulan (payı ≥%15) en çok iki dili dener ve model daha emin olduğu sürümü seçer; kayıtta olmayan bir dil denenmez.
- **Güven işaretleri:** her kelimenin model güveni kaydediliyor. Satırlarda düşük (kırmızı, <0,40) ve orta (sarı, <0,70) güvenli kelimeler renkli işaretlenir; kısa sözcükler ("a", "and") yalnızca çok düşükse. Satırın sol kenarında sarı/kırmızı şerit çıkar; konuşmacı kararı şüpheliyse de (başka bir ses neredeyse aynı kadar yakın) şerit çıkar. Üstteki "Kontrol" çubuğundan yalnızca işaretli satırlar gösterilebilir. Satırı düzeltince ya da konuşmacısını değiştirince işaret kalkar. Gerçek kayıtta 90 satırdan 30'u işaretli (5 kırmızı, 25 sarı); işaretlenenler çoğunlukla özel adlar ("Koriersu") — yani tam da elle düzeltilmesi gereken yerler.

**Kırmızı işaretler azaltıldı (12 Kasım, ikinci ayar):** model sık kullanılan sözcüklerde ("like", "since", "point") doğru yazsa bile güvenini düşük veriyordu; ilk ayarda 90 satırın 5'i kırmızı, 25'i sarıydı. Yeni kurallar: kırmızı kelime <0,20 (kısa ve sık sözcükler yalnızca <0,05); özel ad olabilecek (cümle ortasında büyük harfli) kelimeler daha sıkı (kırmızı <0,30, sarı <0,60); satır kırmızısı için satır güveni <0,55 ya da en az 2 kırmızı kelime; konuşmacı şüphesi yalnızca belirgin farkta (sarı <0,0, kırmızı <-0,05). Aynı kayıtta: kırmızı satır 5 → 2, sarı 25 → 9, kırmızı kelime 27 → 5. Eşikler `frontend/app.js` içindeki `RV` tablosunda.
