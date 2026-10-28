// DSX mod reference client and tester. Requires the .NET 10 SDK; no project or packages.
//
//   dotnet run DsxModClient.cs -- examples/lightbar-and-leds.json
//   dotnet run DsxModClient.cs -- examples/adaptive-triggers.json --pipe
//   dotnet run DsxModClient.cs -- -            (read the packet from stdin)
//
// Options: --pipe (use the DSX.Mod.v1 named pipe instead of UDP), --port <n>, --timeout <ms>.
// The client adds "Diagnostics": true to the packet unless it already sets it, so UDP replies explain problems too.
// Exit code: 0 accepted, 1 DSX reported diagnostics or the packet is not JSON, 2 no reply, 64 usage error.

using System.Buffers.Binary;
using System.IO.Pipes;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

string? packetPath = null;
bool usePipe = false;
int? port = null;
int timeoutMs = 2000;
for (int i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--pipe": usePipe = true; break;
        case "--port" when i + 1 < args.Length && int.TryParse(args[i + 1], out int portValue) && portValue is >= 1 and <= 65535:
            port = portValue; i++; break;
        case "--timeout" when i + 1 < args.Length && int.TryParse(args[i + 1], out int timeoutValue) && timeoutValue is >= 1 and <= 60000:
            timeoutMs = timeoutValue; i++; break;
        default:
            if (args[i].StartsWith("--") || packetPath is not null)
            {
                Console.Error.WriteLine("Usage: dotnet run DsxModClient.cs -- [packet.json | -] [--pipe] [--port 1-65535] [--timeout 1-60000]");
                return 64;
            }
            packetPath = args[i];
            break;
    }
}

string packet = packetPath switch
{
    null => """{"Instructions":[{"Type":"GetDSXStatus","Parameters":[]}]}""",
    "-" => Console.In.ReadToEnd(),
    _ => File.ReadAllText(packetPath)
};
string? localError = null;
try
{
    if (JsonNode.Parse(packet) is not JsonObject json)
    {
        localError = "A DSX packet must be a JSON object with an \"Instructions\" array.";
    }
    else if (!json.Any(static property => string.Equals(property.Key, "Diagnostics", StringComparison.OrdinalIgnoreCase)))
    {
        json["Diagnostics"] = true;
        packet = json.ToJsonString();
    }
}
catch (JsonException exception)
{
    // Send it anyway: the reply shows how DSX treats it.
    localError = $"Not valid JSON (line {exception.LineNumber}, byte {exception.BytePositionInLine}): {exception.Message}";
}
byte[] request = Encoding.UTF8.GetBytes(packet);
if (request.Length is 0 or > 65507)
{
    Console.Error.WriteLine("A DSX mod packet must be between 1 and 65507 bytes of UTF-8 JSON.");
    return 64;
}
using var timeout = new CancellationTokenSource(timeoutMs);

byte[] response;
try
{
    response = usePipe
        ? await SendOverPipeAsync(request, timeout.Token)
        : await SendOverUdpAsync(request, port ?? ReadDsxPort(), timeout.Token);
}
catch (Exception exception) when (exception is OperationCanceledException or IOException or SocketException)
{
    Console.Error.WriteLine(usePipe
        ? "No reply on pipe DSX.Mod.v1. Is DSX running with Settings > Networking > Mod System turned on?"
        : $"No reply on 127.0.0.1:{port ?? ReadDsxPort()}. Is DSX running with Settings > Networking > " +
          "Incoming UDP turned on, and is that port free? (DSX listens on 127.0.0.1 only.)");
    return 2;
}

using JsonDocument reply = JsonDocument.Parse(response);
JsonElement root = reply.RootElement;
Console.WriteLine($"{root.GetProperty("Status").GetString()} at {root.GetProperty("TimeReceived").GetString()}");
foreach (JsonElement device in root.GetProperty("Devices").EnumerateArray())
{
    Console.WriteLine(
        $"  [{device.GetProperty("Index")}] {device.GetProperty("DeviceType")} " +
        $"{device.GetProperty("ConnectionType")} battery {device.GetProperty("BatteryLevel")}%");
}

if (!root.TryGetProperty("Diagnostics", out JsonElement diagnostics))
{
    if (localError is not null)
    {
        Console.WriteLine($"  Packet: {localError}");
        Console.WriteLine("DSX ignored the packet (see above).");
        return 1;
    }
    Console.WriteLine("This DSX version does not report diagnostics.");
    return 0;
}
foreach (JsonElement diagnostic in diagnostics.EnumerateArray())
{
    string where = diagnostic.TryGetProperty("Instruction", out JsonElement index) ? $"Instruction {index}" : "Packet";
    Console.WriteLine($"  {where}: {diagnostic.GetProperty("Code").GetString()} - {diagnostic.GetProperty("Message").GetString()}");
}
Console.WriteLine(diagnostics.GetArrayLength() == 0 ? "Accepted." : "DSX reported problems (see above).");
return diagnostics.GetArrayLength() == 0 ? 0 : 1;

// DSX publishes its current UDP port here; 6969 is the default.
static int ReadDsxPort()
{
    string path = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DSX", "DSX_UDP_PortNumber.txt");
    return File.Exists(path) && int.TryParse(File.ReadAllText(path).Trim(), out int value) ? value : 6969;
}

// One JSON packet per datagram; DSX answers to the sender's address.
static async Task<byte[]> SendOverUdpAsync(byte[] request, int port, CancellationToken cancellationToken)
{
    using var udp = new UdpClient(AddressFamily.InterNetwork);
    udp.Connect(IPAddress.Loopback, port);
    await udp.SendAsync(request, cancellationToken);
    return (await udp.ReceiveAsync(cancellationToken)).Buffer;
}

// Frames are a 4-byte little-endian length followed by that many bytes of UTF-8 JSON, in both directions.
// Keep the connection open and send further packets on it; this sample sends one.
static async Task<byte[]> SendOverPipeAsync(byte[] request, CancellationToken cancellationToken)
{
    await using var pipe = new NamedPipeClientStream(".", "DSX.Mod.v1", PipeDirection.InOut, PipeOptions.Asynchronous);
    await pipe.ConnectAsync(cancellationToken);
    byte[] length = new byte[4];
    BinaryPrimitives.WriteUInt32LittleEndian(length, (uint)request.Length);
    await pipe.WriteAsync(length, cancellationToken);
    await pipe.WriteAsync(request, cancellationToken);
    await pipe.FlushAsync(cancellationToken);

    await pipe.ReadExactlyAsync(length, cancellationToken);
    uint replyLength = BinaryPrimitives.ReadUInt32LittleEndian(length);
    if (replyLength is 0 or > 65507)
    {
        throw new InvalidDataException("The DSX reply frame length is invalid.");
    }
    byte[] response = new byte[replyLength];
    await pipe.ReadExactlyAsync(response, cancellationToken);
    return response;
}
