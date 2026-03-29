# pybroscan

**pybroscan** is a Pythonic adaptation of `brscan-skey` for Brother multifunction printers.

Brother printer/scanner combos are actually pretty good. The only issue is that while printing works great out of the box on Linux on ARM, scanning documents and images is limited to just a few programs.

Things like starting a scan directly from the multifunction printer simply are not possible, which is what prompted me to dissect my printer's protocol and recreate it in Python.

The printer has an option that allows you to select either **File**, **OCR**, **Image**, or **Email** to send the document directly to a computer on the network running the original Brother `brscan-skey`, using preset settings.

This now works not only on Windows/Linux/macOS, but on anything that runs Python.\*

\*I can only say this applies to my printer so far, since I have not been able to test it anywhere else yet.

---

## Features

- Pure Python, no driver or manufacturer software required
- Registering multiple target computers on the Brother multifunction printer
- Scanning from the ADF, including multi-page scans
- Scanning from the flatbed, single-page
- Automatic saving under the configured target computer names
- Easy configuration via `config.ini`
- Separate scan parameters for each category (`File`, `OCR`, `Image`, `Email`)
- All scan settings can be configured via the `config.ini` file


---

## How it works

The basic setup consists of two scripts:

### `brother-register.py`

This script can register multiple "users" with the printer. This means you are not limited to a single destination like with the original `brscan-skey`, but can specify multiple ones.

As a result, appropriate folders are created in your storage location for each specified destination, where the scans are saved.

For example, you can register `Invoices` and `Documents`, and later tap:

`Scan > To File > Invoices > Start`

on the printer, and the scan will be saved in:

```text
../Scans/Invoices/scan_date.jpg
```

It have to repeat the registration every 360 seconds, otherwise the printer will forget the settings and the destination device will no longer be available for selection.


### `brother-listener.py`

This is the script that does the actual work. Once started, it waits for the corresponding buttons on the printer/scanner to be pressed so it can accept the incoming scan data.

This works by listening on a port for a request from the scanner and then starting the scan using the configurable parameters for the individual elements (`File`, `OCR`, `Image`, `Email`).

If something is in the ADF, it is scanned first. If there are multiple pages, a number is appended to the filename in ascending order.

The generated image files are then saved in a structure like this:

```text
/your/desired/path/target_name/file|image|ocr|email/scan_date_time.jpg
```


## Tested on

- Raspberry Pi 4 with DietPi 10.2 and Python 3.13.5


## Tested Brother multifunction printers

- Brother MFC-J4350DW

---

This is still **alpha** software and has not really been tested much yet.

It may work, it may not, or it may work only with adjustments. For that, I would need feedback.

---


## Setup

First, assign a **fixed IP address** to the multifunction printer in your network.

### 1. Prepare Python and install `requests`

```bash
pip install requests
```

### 2. Download the files

Download the following files and place them together in a location of your choice:

- `brother-register.py`
- `brother-listener.py`
- `config.ini`

### 3. Edit `config.ini`

Open `config.ini` and adjust the settings as desired.

### Explanation of the important options

#### `[general]`
- `base_output_dir` >>> Path where the scans will be saved in the appropriate subfolders
- `log_level` >>> Sets the log level

#### `[users]`
- `names` >>> Comma-separated list of users/targets that should appear on the Brother printer

#### `[device]`
- `printer_ip` >>> Fixed IP address of the Brother printer
- `udp_port` >>> UDP port (normally should not need to be changed)
- `scan_port` >>> Port through which the image data is transferred (normally should not need to be changed)

#### `[timing]`
- `post_probe_sleep` >>> Time to wait after establishing contact (normally should not need to be changed)
- `first_data_timeout` >>> Timeout for initial communication problems (normally should not need to be changed)
- `quiet_timeout` >>> If scanning in high resolutions and the PC stops earlier than the scanner, this value can be increased to `60` or more
- `hard_deadline` >>> Timeout after which the scan is finally aborted

#### `[debug]`
- `save_raw_stream` >>> Debug mode: also save the raw stream data
- `save_payload` >>> Debug mode: save the payload separately

#### `[hooks]`
- `post_scan_command` >>> Path to a script file that is executed automatically after a scan has finished

#### `[func:FILE]`
This defines the scan options for the individual modes such as `File`, `OCR`, `Image`, and `Email`. They are always structured the same way, so this is just the example for `File`.

- `folder` >>> Folder name created under the path defined in `[general] base_output_dir`
- `user_subdir` >>> Whether a user subfolder should be used
- `probe_psrc` >>> Printer default; the scanner itself prefers the ADF if documents are present. If the ADF is empty, the flatbed scanner is used
- `resolution` >>> Scan resolution tested so far: `100`, `300`, `600`, `1200`
- `base_area` >>> Base area of the ADF; values are calculated accordingly depending on the resolution

The other values were taken over from the original `brscan-skey` and have not been changed yet.

---




## Usage

After saving the `config.ini` file, start the registration script:

```bash
python brother-register.py
```

After that, the users defined under `[users] names` will be visible on the printer.

Then start the listener script:

```bash
python brother-listener.py
```

Now you should be able to transfer JPG image files directly from your Brother printer via the **Scan** button.

---



## Notes

- This project is currently tested only with one printer model
- Feedback is welcome, especially for other Brother multifunction printers
