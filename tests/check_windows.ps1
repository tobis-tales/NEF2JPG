# Prueft JPGs mit den Windows-eigenen Bibliotheken, so wie Explorer und die Fotos-App sie lesen:
#   1. WIC (BitmapDecoder): vollstaendige Dekodierung und Metadaten (Kamera, Aufnahmedatum)
#   2. GDI+ (System.Drawing): Bild, EXIF-Eintraege, Miniaturbild
#   3. Shell-Bildabruf (IShellItemImageFactory::GetImage), derselbe Weg wie Explorer-Miniaturansicht
#      und Vorschaufenster, in mehreren Groessen und mit verschiedenen Flags
# Aufruf:  powershell -File tests/check_windows.ps1 bild1.jpg bild2.jpg ...
param([Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Files)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName PresentationCore, System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ShellThumb {
    [StructLayout(LayoutKind.Sequential)]
    public struct SIZE { public int cx; public int cy; public SIZE(int x, int y) { cx = x; cy = y; } }
    [ComImport, Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellItemImageFactory { void GetImage(SIZE size, int flags, out IntPtr phbm); }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    public static extern void SHCreateItemFromParsingName(string path, IntPtr pbc, ref Guid riid,
        [MarshalAs(UnmanagedType.Interface)] out IShellItemImageFactory factory);
    [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr h);
    public static IntPtr GetImage(string path, int size, int flags) {
        Guid iid = typeof(IShellItemImageFactory).GUID;
        IShellItemImageFactory f;
        SHCreateItemFromParsingName(path, IntPtr.Zero, ref iid, out f);
        IntPtr hbm;
        f.GetImage(new SIZE(size, size), flags, out hbm);
        return hbm;
    }
}
"@
$flagSets = @(@{ Name = "THUMBNAILONLY"; Value = 0x8 }, @{ Name = "RESIZETOFIT"; Value = 0x0 }, @{ Name = "BIGGERSIZEOK"; Value = 0x1 })
$sizes = @(96, 256, 512, 1024, 2048)
$failed = $false
foreach ($file in $Files) {
    $path = (Resolve-Path $file).Path
    Write-Host "== $path ($([math]::Round((Get-Item $path).Length / 1MB, 2)) MB)"
    try {
        $stream = [System.IO.File]::OpenRead($path)
        $dec = [System.Windows.Media.Imaging.BitmapDecoder]::Create($stream,
            [System.Windows.Media.Imaging.BitmapCreateOptions]::None, [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad)
        $frame = $dec.Frames[0]
        $stride = $frame.PixelWidth * (($frame.Format.BitsPerPixel + 7) -shr 3)
        $pixels = New-Object byte[] ($stride * $frame.PixelHeight)
        $frame.CopyPixels($pixels, $stride, 0)
        $meta = $frame.Metadata
        Write-Host ("   WIC:  {0}x{1} {2}  Kamera='{3}'  Aufnahme='{4}'  vollstaendig dekodiert" -f $frame.PixelWidth, $frame.PixelHeight, $frame.Format, $meta.CameraModel, $meta.DateTaken)
        $stream.Dispose()
    } catch { Write-Host "   WIC FEHLER: $($_.Exception.Message)"; $failed = $true }
    try {
        $img = [System.Drawing.Image]::FromFile($path)
        $thumb = $img.GetThumbnailImage(160, 107, $null, [IntPtr]::Zero)
        Write-Host ("   GDI+: {0}x{1}  EXIF-Eintraege={2}" -f $img.Width, $img.Height, $img.PropertyItems.Count)
        $thumb.Dispose(); $img.Dispose()
    } catch { Write-Host "   GDI+ FEHLER: $($_.Exception.Message)"; $failed = $true }
    foreach ($fs in $flagSets) {
        $parts = @()
        foreach ($size in $sizes) {
            try {
                $h = [ShellThumb]::GetImage($path, $size, $fs.Value)
                $bmp = [System.Drawing.Image]::FromHbitmap($h)
                $parts += ("{0}px ok {1}x{2}" -f $size, $bmp.Width, $bmp.Height)
                $bmp.Dispose(); [ShellThumb]::DeleteObject($h) | Out-Null
            } catch {
                $msg = if ($_.Exception.InnerException) { $_.Exception.InnerException.Message } else { $_.Exception.Message }
                $parts += ("{0}px FEHLER [{1}]" -f $size, $msg.Trim())
                $failed = $true
            }
        }
        Write-Host ("   Shell {0,-14}: {1}" -f $fs.Name, ($parts -join " | "))
    }
}
if ($failed) { Write-Host "MINDESTENS EINE PRUEFUNG FEHLGESCHLAGEN"; exit 1 }
Write-Host "Alle Windows-Pruefungen bestanden"
