# Prueft JPGs mit den Windows-eigenen Bibliotheken, so wie Explorer und die Fotos-App sie lesen:
#   1. WIC (BitmapDecoder): Bild und Metadaten (Kamera, Aufnahmedatum)
#   2. GDI+ (System.Drawing): Bild, EXIF-Eintraege, Miniaturbild
#   3. Explorer-Miniaturansicht: IShellItemImageFactory mit SIIGBF_THUMBNAILONLY
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
    public static void Thumbnail(string path, int size) {
        Guid iid = typeof(IShellItemImageFactory).GUID;
        IShellItemImageFactory f;
        SHCreateItemFromParsingName(path, IntPtr.Zero, ref iid, out f);
        IntPtr hbm;
        f.GetImage(new SIZE(size, size), 0x8, out hbm);   // 0x8 = SIIGBF_THUMBNAILONLY, kein Icon-Ersatz
        DeleteObject(hbm);
    }
}
"@
$failed = $false
foreach ($file in $Files) {
    $path = (Resolve-Path $file).Path
    Write-Host "== $path ($([math]::Round((Get-Item $path).Length / 1MB, 1)) MB)"
    try {
        $stream = [System.IO.File]::OpenRead($path)
        $dec = [System.Windows.Media.Imaging.BitmapDecoder]::Create($stream,
            [System.Windows.Media.Imaging.BitmapCreateOptions]::None, [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad)
        $frame = $dec.Frames[0]
        $meta = $frame.Metadata
        Write-Host ("   WIC:      {0}x{1}  Kamera='{2}'  Aufnahme='{3}'" -f $frame.PixelWidth, $frame.PixelHeight, $meta.CameraModel, $meta.DateTaken)
        $stream.Dispose()
    } catch { Write-Host "   WIC FEHLER: $($_.Exception.Message)"; $failed = $true }
    try {
        $img = [System.Drawing.Image]::FromFile($path)
        $thumb = $img.GetThumbnailImage(160, 107, $null, [IntPtr]::Zero)
        Write-Host ("   GDI+:     {0}x{1}  EXIF-Eintraege={2}" -f $img.Width, $img.Height, $img.PropertyItems.Count)
        $thumb.Dispose(); $img.Dispose()
    } catch { Write-Host "   GDI+ FEHLER: $($_.Exception.Message)"; $failed = $true }
    try {
        [ShellThumb]::Thumbnail($path, 256)
        Write-Host "   Explorer-Miniaturansicht: ok"
    } catch {
        $inner = if ($_.Exception.InnerException) { $_.Exception.InnerException.Message } else { "" }
        Write-Host "   Explorer-Miniaturansicht FEHLER: $($_.Exception.Message) $inner"; $failed = $true
    }
}
if ($failed) { Write-Host "MINDESTENS EINE PRUEFUNG FEHLGESCHLAGEN"; exit 1 }
Write-Host "Alle Windows-Pruefungen bestanden"
