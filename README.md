# WiFi SoundBox

Два отдельных проекта:

| Папка | Назначение | Запуск |
| --- | --- | --- |
| SoundBoxRadio | Сервер, микрофон и веб-пульт | SoundBoxRadio/START_RADIO.cmd |
| SoundBoxFirmware | Прошивка ESP32, бывшая папка Temper1 | SoundBoxFirmware/FLASH_ESP32.cmd |

Актуальный исходник ESP32: **SoundBoxFirmware/src/main.cpp**.
Готовая прошивка: **SoundBoxFirmware/dist/SoundBoxRadio-full.bin**, адрес записи **0x0**.
Пересборка без интернета: **SoundBoxFirmware/BUILD_FIRMWARE.cmd**.

Каждый проект содержит свои необходимые библиотеки и инструменты. Прошивка больше не дублируется в папке сервера.
Подробные инструкции находятся в README.md соответствующих проектов.
