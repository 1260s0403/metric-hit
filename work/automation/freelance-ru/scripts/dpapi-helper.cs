using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

internal static class DpapiHelper
{
    [StructLayout(LayoutKind.Sequential)]
    private struct DataBlob
    {
        public int cbData;
        public IntPtr pbData;
    }

    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(
        ref DataBlob input,
        string description,
        IntPtr optionalEntropy,
        IntPtr reserved,
        IntPtr prompt,
        int flags,
        out DataBlob output);

    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(
        ref DataBlob input,
        IntPtr description,
        IntPtr optionalEntropy,
        IntPtr reserved,
        IntPtr prompt,
        int flags,
        out DataBlob output);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool LocalFree(IntPtr memory);

    private const int CryptprotectUiForbidden = 0x1;

    private static int Main(string[] args)
    {
        if (args.Length != 1 || (args[0] != "protect" && args[0] != "unprotect"))
        {
            Console.Error.WriteLine("Usage: dpapi-helper.exe <protect|unprotect>");
            return 2;
        }

        try
        {
            var inputBytes = Convert.FromBase64String(Console.In.ReadToEnd().Trim());
            var outputBytes = Transform(inputBytes, args[0] == "protect");
            Console.Out.Write(Convert.ToBase64String(outputBytes));
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }

    private static byte[] Transform(byte[] bytes, bool protect)
    {
        var input = new DataBlob { cbData = bytes.Length, pbData = Marshal.AllocHGlobal(bytes.Length) };
        DataBlob output;
        try
        {
            Marshal.Copy(bytes, 0, input.pbData, bytes.Length);
            var success = protect
                ? CryptProtectData(ref input, null, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, CryptprotectUiForbidden, out output)
                : CryptUnprotectData(ref input, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, CryptprotectUiForbidden, out output);
            if (!success) throw new Win32Exception(Marshal.GetLastWin32Error());
            try
            {
                var result = new byte[output.cbData];
                Marshal.Copy(output.pbData, result, 0, output.cbData);
                return result;
            }
            finally
            {
                if (output.pbData != IntPtr.Zero) LocalFree(output.pbData);
            }
        }
        finally
        {
            Marshal.FreeHGlobal(input.pbData);
        }
    }
}
