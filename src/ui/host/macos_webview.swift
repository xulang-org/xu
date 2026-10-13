import AppKit
import WebKit
import Foundation

// #ui/webview content plugin. Linked only when ui.register_content_plugin(webview) runs.
// Registers into XuContentRegistry at load time.

/// Sits above WKWebView: clicks pass through; file drags are intercepted.
final class FileDropOverlay: NSView {
  var onFileDrop: (([String]) -> Void)?

  override var isOpaque: Bool { false }

  override init(frame frameRect: NSRect) {
    super.init(frame: frameRect)
    autoresizingMask = [.width, .height]
    wantsLayer = true
    layer?.backgroundColor = NSColor.clear.cgColor
    registerForDraggedTypes([.fileURL])
  }

  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  private var dragPasteboardHasFiles: Bool {
    let pb = NSPasteboard(name: .drag)
    return pb.canReadObject(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true])
  }

  override func hitTest(_ point: NSPoint) -> NSView? {
    // Only become the target during a file-URL drag; otherwise let WebView get clicks.
    if dragPasteboardHasFiles {
      return self
    }
    return nil
  }

  override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
    sender.draggingPasteboard.canReadObject(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) ? .copy : []
  }

  override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
    draggingEntered(sender)
  }

  override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
    guard let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL] else {
      return false
    }
    let paths = urls.map { $0.path }.filter { !$0.isEmpty }
    if paths.isEmpty { return false }
    onFileDrop?(paths)
    return true
  }
}


/// Same body as webview.bridge_script() / Windows kXuBridgeJs.
/// WKScriptMessageHandlerWithReply: postMessage returns a Promise (no evaluateJavaScript round-trip).
private let kXuBridgeJs = """
window.__XU__=window.__XU__||{};(function(X){function sc(s){s=String(s==null?'':s);if(!s.length)return '!s ';for(var i=0;i<s.length;i++){var c=s.charCodeAt(i);if(c===10||c===13||c===9||c===35||c===58||c===32||c===33||c===64||c===36)return '!s '+s;}return s;}function enc(n,p){return 'name: '+sc(n)+'\\npayload: '+sc(p)+'\\n';}function dec(t){var o={};String(t||'').split('\\n').forEach(function(line){var i=line.indexOf(': ');if(i>0){var k=line.slice(0,i),v=line.slice(i+2);if(v.indexOf('!s ')===0)v=v.slice(3);o[k]=v;}});return o;}var B='xu://app/__xu';X._deliver=function(n,p){var cb=(X._L||{})[n];if(cb)try{cb(p);}catch(e){}};X.invoke=function(n,p){var wh=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.xuInvoke;if(wh){var body={name:String(n==null?'':n),payload:String(p==null?'':p)};var pr=wh.postMessage(body);if(pr&&typeof pr.then==='function')return pr;}return fetch(B+'/invoke',{method:'POST',headers:{'Content-Type':'text/xun; charset=utf-8'},body:enc(n,p)}).then(function(r){return r.text();}).then(function(t){var o=dec(t);if(o.ok==='false'||o.ok==='0')throw new Error(o.error||'error');return o.result!=null?o.result:t;});};X.listen=function(n,cb){(X._L=X._L||{})[n]=cb;};window.invoke=X.invoke;window.listen=function(n,cb){return X.listen(n,cb);};})(window.__XU__);
"""

private enum XuXun {
  static func scalar(_ s: String) -> String {
    if s.isEmpty { return "!s " }
    for ch in s.utf16 {
      if ch == 10 || ch == 13 || ch == 9 || ch == 35 || ch == 58 || ch == 32 || ch == 33 || ch == 64 || ch == 36 {
        return "!s " + s
      }
    }
    return s
  }

  static func encode(name: String, payload: String) -> String {
    "name: \(scalar(name))\npayload: \(scalar(payload))\n"
  }

  static func decode(_ t: String) -> [String: String] {
    var o: [String: String] = [:]
    for line in t.split(separator: "\n", omittingEmptySubsequences: false) {
      let s = String(line)
      guard let i = s.range(of: ": ") else { continue }
      let k = String(s[..<i.lowerBound])
      var v = String(s[i.upperBound...])
      if v.hasPrefix("!s ") { v = String(v.dropFirst(3)) }
      o[k] = v
    }
    return o
  }
}

/// JS → native invoke via WKScriptMessageHandlerWithReply (Promise resolves in-engine).
final class XuInvokeScriptHandler: NSObject, WKScriptMessageHandlerWithReply {
  weak var shell: AppDelegate?

  func userContentController(
    _ userContentController: WKUserContentController,
    didReceive message: WKScriptMessage,
    replyHandler: @escaping (Any?, String?) -> Void
  ) {
    guard message.name == "xuInvoke", let shell = shell else {
      replyHandler(nil, "no host")
      return
    }
    var name = ""
    var payload = ""
    if let d = message.body as? [String: Any] {
      name = d["name"] as? String ?? ""
      payload = d["payload"] as? String ?? ""
    } else if let s = message.body as? String {
      name = s
    }
    let req = XuXun.encode(name: name, payload: payload)
    let t0 = CFAbsoluteTimeGetCurrent()
    shell.xuIpcInvokeAsync(req) { resp in
      let o = XuXun.decode(resp)
      let ok = (o["ok"] != "false" && o["ok"] != "0")
      let totalMs = (CFAbsoluteTimeGetCurrent() - t0) * 1000.0
      if ProcessInfo.processInfo.environment["XU_UI_TIMING"] == "1" {
        fputs(String(format: "xu_ui_timing name=%@ total=%.1fms\n", name, totalMs), stderr)
      }
      if ok {
        replyHandler(o["result"] ?? "", nil)
      } else {
        replyHandler(nil, o["error"] ?? "error")
      }
    }
  }
}

private func xuLoadBridgeJs(shell: AppDelegate) -> Data {
  // Always use the host-embedded bridge so it stays matched to WithReply handler.
  // Packed __xu/bridge.js may lag if only the app binary was rebuilt.
  _ = shell
  return Data(kXuBridgeJs.utf8)
}

/// Custom xu:// scheme: page assets + IPC (no TCP listen).
final class XuSchemeHandler: NSObject, WKURLSchemeHandler {
  weak var shell: AppDelegate?
  private var stopped = Set<ObjectIdentifier>()

  func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
    guard let shell = shell, let url = urlSchemeTask.request.url else {
      urlSchemeTask.didFailWithError(NSError(domain: "xu", code: 1))
      return
    }
    let id = ObjectIdentifier(urlSchemeTask)
    let host = (url.host ?? "").lowercased()
    var path = url.path
    if path.isEmpty { path = "/" }

    // Fold WK quirks: /app.css from xu://app/ may become xu://app.css (host=app.css).
    let route = Self.normalizeRoute(host: host, path: path)

    if route == "/__xu/invoke" || route.hasSuffix("/__xu/invoke") {
      // Intercept → ask Xu worker (mailbox) → finish with response. Never block this thread.
      let body = requestBodyString(urlSchemeTask.request)
      shell.xuIpcInvokeAsync(body) { [weak self] resp in
        guard let self = self else { return }
        self.finish(urlSchemeTask, id: id, data: Data(resp.utf8), mime: "text/xun; charset=utf-8")
      }
      return
    }
    if route == "/__xu/poll" || route.hasSuffix("/__xu/poll") {
      let resp = shell.xuIpcPoll()
      finish(urlSchemeTask, id: id, data: Data(resp.utf8), mime: "text/xun; charset=utf-8")
      return
    }
    if route == "/__xu/bridge.js" || route.hasSuffix("/__xu/bridge.js") {
      finish(urlSchemeTask, id: id, data: xuLoadBridgeJs(shell: shell),
             mime: "application/javascript; charset=utf-8")
      return
    }
    if route.hasPrefix("/brand/") || route == "/favicon.ico" {
      let candidates: [String] = route == "/favicon.ico"
        ? ["brand/xu_classic.svg", "brand/xu_classic.png", "brand/xu_app_logo.png", "brand/xu_app_icon.png"]
        : [String(route.dropFirst())]
      for rel in candidates {
        if let data = xuPackWwwData(rel) ?? xuPackPathData(rel) {
          finish(urlSchemeTask, id: id, data: data, mime: Self.mimeFor(route: "/" + rel))
          return
        }
        let file = (shell.tmp as NSString).appendingPathComponent(rel)
        if let data = try? Data(contentsOf: URL(fileURLWithPath: file)) {
          finish(urlSchemeTask, id: id, data: data, mime: Self.mimeFor(route: "/" + rel))
          return
        }
        if let data = try? Data(contentsOf: URL(fileURLWithPath: rel)) {
          finish(urlSchemeTask, id: id, data: data, mime: Self.mimeFor(route: "/" + rel))
          return
        }
      }
      finish(urlSchemeTask, id: id, data: Data("icon missing\n".utf8), mime: "text/plain", status: 404)
      return
    }
    // xu://app/* (and folded hosts) → static www
    if let data = Self.loadWwwFile(shell: shell, route: route) {
      finish(urlSchemeTask, id: id, data: data, mime: Self.mimeFor(route: route))
      return
    }
    if route == "/" || route == "/index.html" {
      let htmlPath = (shell.tmp as NSString).appendingPathComponent("xu_ui_page.html")
      if let html = try? String(contentsOfFile: htmlPath, encoding: .utf8), !html.isEmpty {
        finish(urlSchemeTask, id: id, data: Data(html.utf8), mime: "text/html; charset=utf-8")
        return
      }
      finish(urlSchemeTask, id: id, data: Data("<html><body>Xu: no page</body></html>".utf8),
             mime: "text/html; charset=utf-8")
      return
    }
    finish(urlSchemeTask, id: id, data: Data("not found\n".utf8), mime: "text/plain", status: 404)
  }

  /// Map xu:// hosts into a www/IPC route. Handles WK absolute-path quirks.
  static func normalizeRoute(host: String, path: String) -> String {
    let p = path.isEmpty ? "/" : path
    if host == "ipc" {
      return "/__xu" + (p.hasPrefix("/") ? p : "/" + p)
    }
    if host == "app" || host.isEmpty {
      return p
    }
    // xu://__xu/invoke → /__xu/invoke; xu://app.css → /app.css
    if p == "/" || p.isEmpty {
      return "/" + host
    }
    return "/" + host + p
  }

  func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {
    stopped.insert(ObjectIdentifier(urlSchemeTask))
  }

  static func mimeFor(route: String) -> String {
    let lower = route.lowercased()
    if lower.hasSuffix(".html") || lower.hasSuffix(".htm") || route == "/" || route.isEmpty {
      return "text/html; charset=utf-8"
    }
    if lower.hasSuffix(".css") { return "text/css; charset=utf-8" }
    if lower.hasSuffix(".js") { return "application/javascript; charset=utf-8" }
    if lower.hasSuffix(".json") { return "application/json; charset=utf-8" }
    if lower.hasSuffix(".svg") { return "image/svg+xml" }
    if lower.hasSuffix(".png") { return "image/png" }
    if lower.hasSuffix(".jpg") || lower.hasSuffix(".jpeg") { return "image/jpeg" }
    if lower.hasSuffix(".webp") { return "image/webp" }
    if lower.hasSuffix(".ico") { return "image/x-icon" }
    if lower.hasSuffix(".woff2") { return "font/woff2" }
    if lower.hasSuffix(".woff") { return "font/woff" }
    return "application/octet-stream"
  }

  /// Packed memory first, then staged overlay / disk www_root.
  static func loadWwwFile(shell: AppDelegate, route: String) -> Data? {
    var rel = route
    if rel.isEmpty || rel == "/" { rel = "/index.html" }
    if rel.contains("..") { return nil }
    // Staged index overlay when source lacked __XU__ / bridge ref.
    if rel == "/index.html" {
      let overlay = (shell.tmp as NSString).appendingPathComponent("xu_ui_www_index.html")
      if let data = try? Data(contentsOf: URL(fileURLWithPath: overlay)), !data.isEmpty {
        return data
      }
    }
    if let packed = xuPackWwwData(rel) { return packed }
    let root = shell.readTrimmed("xu_ui_www_root.txt")
    if root.isEmpty || root == ":mem:" { return nil }
    let path = (root as NSString).appendingPathComponent(String(rel.drop(while: { $0 == "/" })))
    return try? Data(contentsOf: URL(fileURLWithPath: path))
  }

  private func requestBodyString(_ req: URLRequest) -> String {
    guard let body = req.httpBody else {
      if let stream = req.httpBodyStream {
        stream.open()
        defer { stream.close() }
        var data = Data()
        let bufSize = 4096
        let buf = UnsafeMutablePointer<UInt8>.allocate(capacity: bufSize)
        defer { buf.deallocate() }
        while stream.hasBytesAvailable {
          let n = stream.read(buf, maxLength: bufSize)
          if n <= 0 { break }
          data.append(buf, count: n)
        }
        return String(data: data, encoding: .utf8) ?? ""
      }
      return ""
    }
    return String(data: body, encoding: .utf8) ?? ""
  }

  private func finish(_ task: WKURLSchemeTask, id: ObjectIdentifier, data: Data, mime: String, status: Int = 200) {
    if stopped.contains(id) { return }
    let headers = [
      "Content-Type": mime,
      "Content-Length": "\(data.count)",
      "Access-Control-Allow-Origin": "*",
    ]
    let resp = HTTPURLResponse(
      url: task.request.url ?? URL(string: "xu://app/")!,
      statusCode: status,
      httpVersion: "HTTP/1.1",
      headerFields: headers)!
    task.didReceive(resp)
    task.didReceive(data)
    task.didFinish()
  }
}

final class XuWebViewPlugin: NSObject, XuContentPlugin, WKNavigationDelegate, WKDownloadDelegate, WKUIDelegate {
  weak var shell: AppDelegate!
  var web: WKWebView!
  var dropOverlay: FileDropOverlay?
  var lastUrlKey: String = ""
  var lastHtmlKey: String = ""
  var lastWwwRoot: String = ""
  var progressObs: NSKeyValueObservation?
  var lastProgressPct = -1
  var lastDownloadPath: String = ""
  var mediaMuted = false
  var contextMenuEnabled = true
  var schemeHandler: XuSchemeHandler?
  var invokeHandler: XuInvokeScriptHandler?
  var wantsDevToolsMenu: Bool { true }

  init(shell: AppDelegate) {
    self.shell = shell
    super.init()
  }

  func install(into root: NSView, host: AppDelegate) {
    self.shell = host
    let config = WKWebViewConfiguration()
    // xu://app/* → XuSchemeHandler returns www + /__xu (no HTTP server).
    let handler = XuSchemeHandler()
    handler.shell = host
    config.setURLSchemeHandler(handler, forURLScheme: "xu")
    self.schemeHandler = handler
    // Fast invoke: WithReply so JS postMessage Promise resolves without eval round-trip.
    let inv = XuInvokeScriptHandler()
    inv.shell = host
    config.userContentController.addScriptMessageHandler(inv, contentWorld: .page, name: "xuInvoke")
    self.invokeHandler = inv
    let web = WKWebView(frame: root.bounds, configuration: config)
    web.autoresizingMask = [.width, .height]
    web.allowsMagnification = true
    web.allowsBackForwardNavigationGestures = true
    root.addSubview(web)
    self.web = web
    let wantClear = host.readTrimmed("xu_ui_transparent.txt") == "1"
    web.setValue(!wantClear, forKey: "drawsBackground")
    if #available(macOS 12.0, *) {
      web.underPageBackgroundColor = wantClear ? .clear : NSColor(calibratedRed: 0.06, green: 0.09, blue: 0.16, alpha: 1)
    }
    let drop = FileDropOverlay(frame: root.bounds)
    root.addSubview(drop)
    drop.onFileDrop = { [weak self] paths in
      self?.onFilesDropped(paths)
    }
    self.dropOverlay = drop
    setupWebKit()
    lastWwwRoot = shell.readTrimmed("xu_ui_www_root.txt")
    lastUrlKey = shell.readTrimmed("xu_ui_page.url")
    lastHtmlKey = shell.readTrimmed("xu_ui_page.html")
    let urlPath = (shell.tmp as NSString).appendingPathComponent("xu_ui_page.url")
    let htmlPath = (shell.tmp as NSString).appendingPathComponent("xu_ui_page.html")
    let scheme = shell.readTrimmed("xu_ui_scheme.txt")
    if let u = try? String(contentsOfFile: urlPath, encoding: .utf8) {
      let trimmed = u.trimmingCharacters(in: .whitespacesAndNewlines)
      // Local xu:// mode only when URL is app scheme or scheme flag is xu without remote http(s).
      if isAppXuURL(trimmed) || (scheme == "xu" && !isRemoteHTTP(trimmed)) {
        loadXuDocument(trimmed.isEmpty ? "xu://app/" : trimmed)
        return
      }
      if let url = URL(string: trimmed), !trimmed.isEmpty {
        ensureBridgeUserScript()
        lastUrlKey = trimmed
        web.load(URLRequest(url: url))
        syncWebFrame()
        return
      }
    }
    if let html = try? String(contentsOfFile: htmlPath, encoding: .utf8), html.count > 0 {
      if scheme == "xu" {
        loadXuDocument("xu://app/")
      } else {
        ensureBridgeUserScript()
        web.loadHTMLString(html, baseURL: nil)
      }
    } else if scheme == "xu" {
      loadXuDocument("xu://app/")
    }
  }

  func isRemoteHTTP(_ s: String) -> Bool {
    (s.hasPrefix("http://") || s.hasPrefix("https://")) && !isAppXuURL(s)
  }

  func isAppXuURL(_ s: String) -> Bool {
    s.hasPrefix("xu://") || s.hasPrefix("http://app.xu") || s.hasPrefix("https://app.xu")
  }

  /// Map legacy http://app.xu/… → xu://app/…
  func normalizeAppXuURL(_ s: String) -> String {
    if s.hasPrefix("xu://") { return s }
    if s.hasPrefix("http://app.xu") || s.hasPrefix("https://app.xu") {
      if let u = URL(string: s) {
        var path = u.path
        if path.isEmpty { path = "/" }
        if let q = u.query, !q.isEmpty { return "xu://app\(path)?\(q)" }
        return "xu://app\(path)"
      }
      return "xu://app/"
    }
    return "xu://app/"
  }

  func ensureBridgeUserScript() {
    guard let shell = shell else { return }
    let bridgeData = xuLoadBridgeJs(shell: shell)
    guard let bridge = String(data: bridgeData, encoding: .utf8), !bridge.isEmpty else { return }
    let marker = "/*__XU_BRIDGE__*/"
    let src = marker + "\n" + bridge
    let existing = web.configuration.userContentController.userScripts.contains {
      $0.source.contains("__XU_BRIDGE__")
    }
    if existing { return }
    let script = WKUserScript(source: src, injectionTime: .atDocumentStart, forMainFrameOnly: true)
    web.configuration.userContentController.addUserScript(script)
  }

  func loadXuDocument(_ urlString: String) {
    ensureBridgeUserScript()
    let u = normalizeAppXuURL(urlString.isEmpty ? "xu://app/" : urlString)
    lastUrlKey = u
    if let url = URL(string: u) {
      web.load(URLRequest(url: url))
      syncWebFrame()
    }
  }

  func onPoll() {
    drainEval()
    drainPage()
    pushEmits()
  }

  /// Host pushes emits into the page (no JS setInterval + xu://poll hammering).
  func pushEmits() {
    guard let shell = shell else { return }
    for _ in 0..<16 {
      let t = shell.xuIpcPoll()
      if t.isEmpty { break }
      let o = XuXun.decode(t)
      let n = o["name"] ?? ""
      let p = o["payload"] ?? ""
      guard let data = try? JSONSerialization.data(withJSONObject: [n, p]),
            let json = String(data: data, encoding: .utf8) else { continue }
      web.evaluateJavaScript(
        "window.__XU__&&window.__XU__._deliver&&window.__XU__._deliver.apply(null,\(json));",
        completionHandler: nil)
    }
  }

  func syncFrame() {
    syncWebFrame()
  }

  func evalJS(_ js: String) {
    web.evaluateJavaScript(js, completionHandler: nil)
  }

  func snapshotPNG(to path: String, completion: @escaping (Bool) -> Void) {
    try? "".write(toFile: path, atomically: true, encoding: .utf8)
    web.takeSnapshot(with: nil) { image, _ in
      guard let image = image,
            let tiff = image.tiffRepresentation,
            let rep = NSBitmapImageRep(data: tiff),
            let png = rep.representation(using: .png, properties: [:]) else {
        completion(false)
        return
      }
      do {
        try png.write(to: URL(fileURLWithPath: path))
        completion(true)
      } catch {
        completion(false)
      }
    }
  }

  func snapshotClipboard(completion: @escaping (Bool) -> Void) {
    web.takeSnapshot(with: nil) { image, _ in
      guard let image = image else {
        completion(false)
        return
      }
      NSPasteboard.general.clearContents()
      NSPasteboard.general.writeObjects([image])
      completion(true)
    }
  }

  /// Returns true if the command was a webview/content command.
  @discardableResult
  func handleCmd(_ s: String) -> Bool {
    if s == "reload" {
      web.reload()
      return true
    }
    if s == "back" {
      if web.canGoBack { web.goBack() }
      return true
    }
    if s == "forward" {
      if web.canGoForward { web.goForward() }
      return true
    }
    if s == "stop" {
      web.stopLoading()
      return true
    }
    if s == "print" {
      printPage()
      return true
    }
    if s == "clear_cache" {
      clearCache()
      return true
    }
    if s == "cookies_get" {
      getCookies()
      return true
    }
    if s == "cookies_clear" {
      clearCookiesOnly()
      return true
    }
    if s == "cookie_set" {
      setCookieFromFile()
      return true
    }
    if s.hasPrefix("magnify\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        let on = parts[1] != "0"
        web.allowsMagnification = on
        if !on {
          web.magnification = 1.0
        }
      }
      return true
    }
    if s == "mute" {
      setMediaMuted(true)
      return true
    }
    if s == "unmute" {
      setMediaMuted(false)
      return true
    }
    if s.hasPrefix("bgcolor\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        applyBackground(hex: String(parts[1]))
      }
      return true
    }
    if s.hasPrefix("context_menu\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        let on = parts[1] != "0"
        contextMenuEnabled = on
        applyContextMenuFlagToPage()
      }
      return true
    }
    if s == "find" {
      findInPage()
      return true
    }
    if s == "find_clear" {
      clearFind()
      return true
    }
    if s == "inject_css" {
      injectCSS()
      return true
    }
    if s == "set_ua" {
      let ua = shell.readTrimmed("xu_ui_ua.txt")
      web.customUserAgent = ua.isEmpty ? nil : ua
      return true
    }
    if s == "devtools" {
      openDevTools()
      return true
    }
    if s.hasPrefix("zoom\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2, let z = Double(parts[1]), z > 0.1, z < 10 {
        if #available(macOS 11.0, *) {
          web.pageZoom = CGFloat(z)
        }
      }
      return true
    }
    return false
  }

  func setupWebKit() {
    web.navigationDelegate = self
    web.uiDelegate = self
    if #available(macOS 13.3, *) {
      web.isInspectable = true
    }
    web.configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
    applyContextMenuScript(enabled: true)
    progressObs = web.observe(\.estimatedProgress, options: [.new]) { [weak self] wv, _ in
      self?.onProgress(wv.estimatedProgress)
    }
  }

  func onProgress(_ p: Double) {
    var pct = Int((p * 100.0).rounded())
    if pct < 0 { pct = 0 }
    if pct > 100 { pct = 100 }
    // Always surface 0 and 100; throttle mid values to ~10% steps (local pages jump fast).
    let step = (pct == 0 || pct == 100 || lastProgressPct < 0)
      || abs(pct - lastProgressPct) >= 10
    if !step { return }
    if pct == lastProgressPct { return }
    lastProgressPct = pct
    shell.appendShellFile("progress\t\(pct)")
    web.evaluateJavaScript(
      """
      (function(){
        var bar=document.getElementById('xu_prog');
        var fill=document.getElementById('xu_prog_fill');
        var label=document.getElementById('xu_prog_label');
        if(bar){bar.style.opacity='1';}
        if(fill){fill.style.width='\(pct)%';}
        if(label){label.textContent='loading \(pct)%';}
        if(\(pct)>=100){
          setTimeout(function(){if(bar)bar.style.opacity='0';},400);
        }
      })();
      """,
      completionHandler: nil)
  }

  func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
    lastProgressPct = -1
    shell.appendShellFile("loading")
    shell.appendShellFile("progress\t0")
    web.evaluateJavaScript(
      """
      (function(){
        var bar=document.getElementById('xu_prog');
        var fill=document.getElementById('xu_prog_fill');
        var label=document.getElementById('xu_prog_label');
        if(bar){bar.style.opacity='1';}
        if(fill){fill.style.width='0%';}
        if(label){label.textContent='loading 0%';}
      })();
      """,
      completionHandler: nil)
  }

  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    shell.appendShellFile("loaded")
    syncWebFrame()
    if mediaMuted {
      setMediaMuted(true)
    }
    applyContextMenuFlagToPage()
  }

  func applyContextMenuScript(enabled: Bool) {
    contextMenuEnabled = enabled
    let js = """
    (function(){
      window.__XU_CTX__=\(enabled ? "true" : "false");
      if(!window.__XU_CTX_HOOK__){
        window.__XU_CTX_HOOK__=true;
        document.addEventListener('contextmenu',function(e){
          if(!window.__XU_CTX__){e.preventDefault();e.stopPropagation();}
        },true);
      }
    })();
    """
    let script = WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: false)
    web.configuration.userContentController.addUserScript(script)
    applyContextMenuFlagToPage()
  }

  func applyContextMenuFlagToPage() {
    let flag = contextMenuEnabled ? "true" : "false"
    web.evaluateJavaScript(
      "window.__XU_CTX__=\(flag);",
      completionHandler: nil)
  }

  func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
    shell.appendShellFile("load_failed")
  }

  func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
    shell.appendShellFile("load_failed")
  }

  func webView(
    _ webView: WKWebView,
    decidePolicyFor navigationResponse: WKNavigationResponse,
    decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
  ) {
    // Custom xu:// often reports canShowMIMEType=false → would download and leave WebView blank.
    if let scheme = navigationResponse.response.url?.scheme?.lowercased(), scheme == "xu" {
      decisionHandler(.allow)
      return
    }
    if !navigationResponse.canShowMIMEType {
      decisionHandler(.download)
      return
    }
    decisionHandler(.allow)
  }

  func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
    download.delegate = self
  }

  func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
    download.delegate = self
  }

  func download(
    _ download: WKDownload,
    decideDestinationUsing response: URLResponse,
    suggestedFilename: String,
    completionHandler: @escaping (URL?) -> Void
  ) {
    let downloads = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
      ?? URL(fileURLWithPath: NSTemporaryDirectory())
    var dest = downloads.appendingPathComponent(suggestedFilename)
    var n = 1
    let base = (suggestedFilename as NSString).deletingPathExtension
    let ext = (suggestedFilename as NSString).pathExtension
    while FileManager.default.fileExists(atPath: dest.path) {
      let name = ext.isEmpty ? "\(base)-\(n)" : "\(base)-\(n).\(ext)"
      dest = downloads.appendingPathComponent(name)
      n += 1
    }
    lastDownloadPath = dest.path
    completionHandler(dest)
  }

  func downloadDidFinish(_ download: WKDownload) {
    let path = lastDownloadPath
    shell.appendShellFile("download\t\(path)")
    let safe = path
      .replacingOccurrences(of: "\\", with: "\\\\")
      .replacingOccurrences(of: "'", with: "\\'")
    web.evaluateJavaScript(
      "var el=document.getElementById('out');if(el)el.textContent='download: \(safe)';",
      completionHandler: nil)
  }

  func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
    shell.appendShellFile("download_failed\t\(error.localizedDescription)")
  }

  func webView(
    _ webView: WKWebView,
    decidePolicyFor navigationAction: WKNavigationAction,
    decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
  ) {
    if #available(macOS 11.3, *) {
      if navigationAction.shouldPerformDownload {
        decisionHandler(.download)
        return
      }
    }
    // User-clicked http(s) links off localhost → system browser (except download-like files).
    if navigationAction.navigationType == .linkActivated,
       let url = navigationAction.request.url,
       let scheme = url.scheme?.lowercased(),
       scheme == "http" || scheme == "https" {
      let host = (url.host ?? "").lowercased()
      if host != "127.0.0.1" && host != "localhost" && host != "::1" {
        let path = url.path.lowercased()
        let dl = [".pdf", ".zip", ".dmg", ".pkg", ".gz", ".tgz", ".xz", ".7z", ".rar",
                  ".exe", ".msi", ".deb", ".rpm", ".iso", ".csv", ".xlsx", ".docx"]
        if dl.contains(where: { path.hasSuffix($0) }) {
          decisionHandler(.allow)
          return
        }
        NSWorkspace.shared.open(url)
        shell.appendShellFile("external_nav\t\(url.absoluteString)")
        decisionHandler(.cancel)
        return
      }
    }
    decisionHandler(.allow)
  }

  @objc func onDevToolsMenu(_ sender: Any?) {
    openDevTools()
  }

  func openDevTools() {
    if #available(macOS 13.3, *) {
      web.isInspectable = true
    }
    web.configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
    // Public API only enables Safari Develop attachment; open via private _WKInspector.
    guard let inspector = web.value(forKey: "_inspector") as AnyObject? else { return }
    let show = NSSelectorFromString("show")
    if inspector.responds(to: show) {
      _ = inspector.perform(show)
    }
  }

  func syncWebFrame() {
    guard let root = shell.window.contentView else { return }
    let b = root.bounds
    if web.frame != b {
      web.frame = b
    }
    root.layoutSubtreeIfNeeded()
  }

  func drainEval() {
    let path = (shell.tmp as NSString).appendingPathComponent("xu_ui_eval.js")
    guard let raw = try? String(contentsOfFile: path, encoding: .utf8) else { return }
    let js = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    if js.isEmpty { return }
    try? "".write(toFile: path, atomically: true, encoding: .utf8)
    let wantPath = (shell.tmp as NSString).appendingPathComponent("xu_ui_eval_want.txt")
    let want = ((try? String(contentsOfFile: wantPath, encoding: .utf8)) ?? "")
      .trimmingCharacters(in: .whitespacesAndNewlines)
    try? "".write(toFile: wantPath, atomically: true, encoding: .utf8)
    if want == "1" {
      let outPath = (shell.tmp as NSString).appendingPathComponent("xu_ui_eval_result.txt")
      web.evaluateJavaScript(js) { result, error in
        var out = ""
        if let error = error {
          out = "err:" + error.localizedDescription
        } else if let s = result as? String {
          out = s
        } else if let n = result as? NSNumber {
          out = n.stringValue
        } else if let b = result as? Bool {
          out = b ? "true" : "false"
        } else if result == nil {
          out = ""
        } else {
          out = String(describing: result!)
        }
        try? out.write(toFile: outPath, atomically: true, encoding: .utf8)
      }
    } else {
      web.evaluateJavaScript(js, completionHandler: nil)
    }
  }

  func setMediaMuted(_ muted: Bool) {
    mediaMuted = muted
    let flag = muted ? "true" : "false"
    let label = muted ? "muted" : "unmuted"
    web.evaluateJavaScript(
      """
      (function(){
        window.__XU_MUTED__=\(flag);
        document.querySelectorAll('video,audio').forEach(function(e){
          e.muted=\(flag);
          e.defaultMuted=\(flag);
          e.volume=\(muted ? "0" : "1");
        });
        if(window.__XU_AUDIO_CTX__){
          if(\(flag)){try{window.__XU_AUDIO_CTX__.suspend()}catch(e){}}
          else{try{window.__XU_AUDIO_CTX__.resume()}catch(e){}}
        }
        var b=document.getElementById('xu_mute_badge');
        if(b){
          b.textContent='\(label)';
          b.style.background=\(muted ? "'#7f1d1d'" : "'#14532d'");
          b.style.opacity='1';
        }
        var el=document.getElementById('out');
        if(el)el.textContent='\(label)';
      })();
      """,
      completionHandler: nil)
    // Best-effort WebKit page mute (selector varies by OS).
    for name in ["setMediaMuted:", "_setPageMuted:", "setMuted:"] {
      let sel = NSSelectorFromString(name)
      if web.responds(to: sel) {
        web.perform(sel, with: muted ? 1 : 0)
        break
      }
    }
    if web.responds(to: NSSelectorFromString("setMediaMuted:")) {
      web.setValue(muted, forKey: "mediaMuted")
    }
  }

  func applyBackground(hex: String) {
    var h = hex.trimmingCharacters(in: .whitespacesAndNewlines)
    if h.hasPrefix("#") { h = String(h.dropFirst()) }
    guard h.count == 6, let n = UInt32(h, radix: 16) else { return }
    let r = CGFloat((n >> 16) & 0xff) / 255
    let g = CGFloat((n >> 8) & 0xff) / 255
    let b = CGFloat(n & 0xff) / 255
    let color = NSColor(calibratedRed: r, green: g, blue: b, alpha: 1)
    shell.window.backgroundColor = color
    if #available(macOS 12.0, *) {
      web.underPageBackgroundColor = color
    }
    // Page CSS covers the shell.window — inject so the change is actually visible.
    let cssHex = "#" + h
    web.evaluateJavaScript(
      """
      (function(){
        var s=document.getElementById('__xu_bg_css');
        if(!s){s=document.createElement('style');s.id='__xu_bg_css';document.documentElement.appendChild(s);}
        s.textContent='html,body{background:\(cssHex) !important;background-image:none !important}';
        var el=document.getElementById('out');
        if(el)el.textContent='bg \(cssHex)';
      })();
      """,
      completionHandler: nil)
  }

  func clearCache() {
    let types: Set<String> = [
      WKWebsiteDataTypeDiskCache,
      WKWebsiteDataTypeMemoryCache,
      WKWebsiteDataTypeCookies,
      WKWebsiteDataTypeLocalStorage,
    ]
    let since = Date(timeIntervalSince1970: 0)
    WKWebsiteDataStore.default().removeData(ofTypes: types, modifiedSince: since) { [weak self] in
      self?.shell.appendShellFile("cache_cleared")
    }
  }

  func clearCookiesOnly() {
    let types: Set<String> = [WKWebsiteDataTypeCookies]
    let since = Date(timeIntervalSince1970: 0)
    WKWebsiteDataStore.default().removeData(ofTypes: types, modifiedSince: since) { [weak self] in
      self?.shell.appendShellFile("cookies_cleared")
      self?.web.evaluateJavaScript(
        "var el=document.getElementById('out');if(el)el.textContent='cookies cleared';",
        completionHandler: nil)
    }
  }

  func getCookies() {
    let out = (shell.tmp as NSString).appendingPathComponent("xu_ui_cookies.txt")
    WKWebsiteDataStore.default().httpCookieStore.getAllCookies { cookies in
      let body = cookies.map { c in
        "\(c.name)=\(c.value);domain=\(c.domain);path=\(c.path)"
      }.joined(separator: "\n")
      try? body.write(toFile: out, atomically: true, encoding: .utf8)
      let n = cookies.count
      DispatchQueue.main.async {
        self.web.evaluateJavaScript(
          "var el=document.getElementById('out');if(el)el.textContent='cookies: \(n)';",
          completionHandler: nil)
      }
    }
  }

  func setCookieFromFile() {
    let path = (shell.tmp as NSString).appendingPathComponent("xu_ui_cookie_set.txt")
    let raw = ((try? String(contentsOfFile: path, encoding: .utf8)) ?? "")
      .trimmingCharacters(in: .whitespacesAndNewlines)
    let parts = raw.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
    guard parts.count >= 2, !parts[0].isEmpty else { return }
    let name = parts[0]
    let value = parts[1]
    let domain = parts.count >= 3 && !parts[2].isEmpty ? parts[2] : "127.0.0.1"
    let props: [HTTPCookiePropertyKey: Any] = [
      .name: name,
      .value: value,
      .domain: domain,
      .path: "/",
    ]
    guard let cookie = HTTPCookie(properties: props) else { return }
    WKWebsiteDataStore.default().httpCookieStore.setCookie(cookie) { [weak self] in
      self?.shell.appendShellFile("cookie_set\t\(name)")
      self?.web.evaluateJavaScript(
        "var el=document.getElementById('out');if(el)el.textContent='cookie set: \(name)';",
        completionHandler: nil)
    }
  }

  func findInPage() {
    let path = (shell.tmp as NSString).appendingPathComponent("xu_ui_find.txt")
    let text = ((try? String(contentsOfFile: path, encoding: .utf8)) ?? "")
      .trimmingCharacters(in: .whitespacesAndNewlines)
    let out = (shell.tmp as NSString).appendingPathComponent("xu_ui_find_result.txt")
    if text.isEmpty {
      clearFind()
      try? "0".write(toFile: out, atomically: true, encoding: .utf8)
      return
    }
    if #available(macOS 11.0, *) {
      let cfg = WKFindConfiguration()
      web.find(text, configuration: cfg) { result in
        let v = result.matchFound ? "1" : "0"
        try? v.write(toFile: out, atomically: true, encoding: .utf8)
      }
    } else {
      let esc = text
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "'", with: "\\'")
      web.evaluateJavaScript("window.find('\(esc)',false,false,true,false,false,false)") { result, _ in
        let ok = (result as? Bool) == true
        try? (ok ? "1" : "0").write(toFile: out, atomically: true, encoding: .utf8)
      }
    }
  }

  func clearFind() {
    if #available(macOS 11.0, *) {
      let cfg = WKFindConfiguration()
      web.find("", configuration: cfg, completionHandler: { _ in })
    }
    web.evaluateJavaScript(
      "if(window.getSelection){var s=window.getSelection();if(s)s.removeAllRanges();}",
      completionHandler: nil)
  }

  func injectCSS() {
    let path = (shell.tmp as NSString).appendingPathComponent("xu_ui_inject.css")
    let css = (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
    if css.isEmpty { return }
    let esc = css
      .replacingOccurrences(of: "\\", with: "\\\\")
      .replacingOccurrences(of: "`", with: "\\`")
      .replacingOccurrences(of: "$", with: "\\$")
    let js = """
    (function(){
      var s=document.getElementById('__xu_inject_css');
      if(!s){s=document.createElement('style');s.id='__xu_inject_css';document.documentElement.appendChild(s);}
      s.textContent=`\(esc)`;
    })();
    """
    web.evaluateJavaScript(js, completionHandler: nil)
  }

  func printPage() {
    let info = NSPrintInfo.shared
    let op = web.printOperation(with: info)
    op.showsPrintPanel = true
    op.showsProgressPanel = true
    op.runModal(for: shell.window, delegate: nil, didRun: nil, contextInfo: nil)
  }

  func onFilesDropped(_ paths: [String]) {
    let joined = paths.joined(separator: "\t")
    let out = (shell.tmp as NSString).appendingPathComponent("xu_ui_drop.txt")
    try? joined.write(toFile: out, atomically: true, encoding: .utf8)
    shell.appendShellFile("file_drop\t\(joined)")
    let safe = paths.joined(separator: ", ")
      .replacingOccurrences(of: "\\", with: "\\\\")
      .replacingOccurrences(of: "'", with: "\\'")
      .replacingOccurrences(of: "\n", with: " ")
    web.evaluateJavaScript(
      "var el=document.getElementById('out');if(el)el.textContent='drop: \(safe)';",
      completionHandler: nil)
  }

  func drainPage() {
    let urlVal = shell.readTrimmed("xu_ui_page.url")
    let htmlVal = shell.readTrimmed("xu_ui_page.html")
    let www = shell.readTrimmed("xu_ui_www_root.txt")
    let scheme = shell.readTrimmed("xu_ui_scheme.txt")
    if !www.isEmpty && www != lastWwwRoot {
      lastWwwRoot = www
      let u = isAppXuURL(urlVal) ? urlVal : (scheme == "xu" && !isRemoteHTTP(urlVal) ? "xu://app/" : "")
      if !u.isEmpty {
        loadXuDocument(u)
        return
      }
    }
    if !urlVal.isEmpty && urlVal != lastUrlKey {
      if isAppXuURL(urlVal) || (scheme == "xu" && !isRemoteHTTP(urlVal)) {
        loadXuDocument(urlVal.isEmpty ? "xu://app/" : urlVal)
        return
      }
      lastUrlKey = urlVal
      lastHtmlKey = htmlVal
      ensureBridgeUserScript()
      if let url = URL(string: urlVal) {
        web.load(URLRequest(url: url))
        syncWebFrame()
      }
      return
    }
    if isAppXuURL(urlVal) || (scheme == "xu" && !isRemoteHTTP(urlVal)) {
      if !htmlVal.isEmpty && htmlVal != lastHtmlKey {
        loadXuDocument(urlVal.isEmpty ? "xu://app/" : urlVal)
      }
      return
    }
    if !htmlVal.isEmpty && htmlVal != lastHtmlKey {
      lastHtmlKey = htmlVal
      lastUrlKey = ""
      ensureBridgeUserScript()
      web.loadHTMLString(htmlVal, baseURL: nil)
    }
  }


}

@objc(XuWebViewPluginBootstrap)
public class XuWebViewPluginBootstrap: NSObject {
  @objc public static func registerPlugin() {
    XuContentRegistry.make = { host in XuWebViewPlugin(shell: host) }
  }
}