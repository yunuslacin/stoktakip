# Stok Takip Uygulaması

Bu proje, FIFO yöntemine göre stok giriş ve çıkışlarını yöneten, çok kullanıcılı bir web tabanlı stok takip çözümüdür. Uygulama Django ile geliştirilmiştir ve aşağıdaki temel özellikleri içerir:

- Stok girişleri için depo, tedarikçi ve fatura bilgisi takibi
- FIFO'ya göre stok düşümü ve proje bazlı çıkış kaydı
- Stok talepleri için hiyerarşik onay süreci
- Düşük stok uyarıları, stok düzeltmeleri ve hareket geçmişi
- Kullanıcı aktivite logları, fiyat geçmişi ve kapsamlı raporlar

## Kurulum

1. Bağımlılıkları yükleyin:

   ```bash
   pip install -r requirements.txt  # requirements dosyası yoksa `pip install django==4.2.6` yeterlidir
   ```

2. Veritabanı tablolarını oluşturmak için migrasyonları çalıştırın:

   ```bash
   python manage.py migrate
   ```

3. Yönetici kullanıcısı oluşturun:

   ```bash
   python manage.py createsuperuser
   ```

4. Geliştirme sunucusunu başlatın:

   ```bash
   python manage.py runserver
   ```

Ardından `http://127.0.0.1:8000` adresine giderek uygulamayı kullanmaya başlayabilirsiniz.

## Test Verisi

Gerekirse `python manage.py createsuperuser` ile oluşturduğunuz yönetici hesabıyla giriş yaptıktan sonra depo, proje, ürün ve kullanıcı ilişkilerini yönetim panellerinden ekleyebilirsiniz.
