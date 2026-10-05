using System.Text.Json;
using Aster.Play;

var builder = WebApplication.CreateBuilder(new WebApplicationOptions { Args = args, ContentRootPath = AppContext.BaseDirectory });
string address = builder.Configuration["urls"] ?? "http://127.0.0.1:5188";
if (!Uri.TryCreate(address, UriKind.Absolute, out var uri) || !uri.IsLoopback || uri.Scheme != "http")
    throw new ArgumentException("Aster Play requires one local HTTP address, e.g. http://127.0.0.1:5188.");
builder.WebHost.UseUrls(address);
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = 32768);
builder.Services.AddSingleton<Game>();
var app = builder.Build();
app.Use(async (context, next) =>
{
    context.Response.Headers["X-Content-Type-Options"] = "nosniff";
    context.Response.Headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'";
    if (context.Request.Method == "POST" && context.Request.Headers.Origin is { Count: > 0 } origin
        && origin.ToString() != $"{context.Request.Scheme}://{context.Request.Host}")
    { context.Response.StatusCode = 403; return; }
    try { await next(context); }
    catch (Exception error) when (error is ArgumentException or FormatException or InvalidOperationException)
    {
        if (context.Response.HasStarted) throw;
        context.Response.StatusCode = error is InvalidOperationException ? 409 : 400;
        await context.Response.WriteAsJsonAsync(new { error = error.Message });
    }
});
app.UseDefaultFiles(); app.UseStaticFiles();
app.MapGet("/api/state", (Game game) => game.Snapshot());
app.MapPost("/api/new", async (NewGame request, Game game) => await game.NewAsync(request));
app.MapPost("/api/move", async (PlayMove request, Game game) => await game.MoveAsync(request.Move));
app.MapPost("/api/undo", async (Game game) => await game.UndoAsync());
app.MapPost("/api/stop", async (Game game) => await game.StopAsync());
app.MapPost("/api/analyze", async (Game game) => await game.AnalyzeAsync());
app.MapPost("/api/settings", (Settings request, Game game) => game.Configure(request.Milliseconds));
app.MapGet("/api/pgn", (Game game) => Results.Text(game.Pgn(), "application/x-chess-pgn"));
app.MapGet("/api/events", async (HttpContext context, Game game) =>
{
    context.Response.ContentType = "text/event-stream";
    context.Response.Headers.CacheControl = "no-cache";
    context.Response.Headers["X-Accel-Buffering"] = "no";
    var subscription = game.Subscribe();
    try
    {
        var initial = game.Snapshot();
        await context.Response.WriteAsync($"id: {initial.Revision}\nevent: state\ndata: " + JsonSerializer.Serialize(initial, Game.Json) + "\n\n", context.RequestAborted);
        await context.Response.Body.FlushAsync(context.RequestAborted);
        await foreach (var message in subscription.Reader.ReadAllAsync(context.RequestAborted))
        {
            await context.Response.WriteAsync($"id: {message.Sequence}\nevent: {message.Kind}\ndata: {message.Json}\n\n", context.RequestAborted);
            await context.Response.Body.FlushAsync(context.RequestAborted);
        }
    }
    catch (OperationCanceledException) when (context.RequestAborted.IsCancellationRequested) { }
    finally { game.Unsubscribe(subscription); }
});
app.Lifetime.ApplicationStopping.Register(() => app.Services.GetRequiredService<Game>().Cancel());
app.Run();
