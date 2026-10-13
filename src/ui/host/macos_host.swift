import AppKit
import UserNotifications
import QuartzCore
import Darwin

// Packed www/icon blobs live in the binary (xu_pack_assets.c). No TEMP extract.
@_silgen_name("xu_pack_www_ptr")
func xu_pack_www_ptr(_ rel: UnsafePointer<CChar>?, _ len: UnsafeMutablePointer<UInt32>?) -> UnsafePointer<UInt8>?

@_silgen_name("xu_pack_icon_ptr")
func xu_pack_icon_ptr(_ len: UnsafeMutablePointer<UInt32>?) -> UnsafePointer<UInt8>?

@_silgen_name("xu_pack_path_ptr")
func xu_pack_path_ptr(_ path: UnsafePointer<CChar>?, _ len: UnsafeMutablePointer<UInt32>?) -> UnsafePointer<UInt8>?

@_silgen_name("xu_ui_mem_set")
func xu_ui_mem_set(_ name: UnsafePointer<CChar>?, _ body: UnsafePointer<CChar>?)

@_silgen_name("xu_ui_mem_get")
func xu_ui_mem_get(_ name: UnsafePointer<CChar>?, _ out: UnsafeMutablePointer<CChar>?, _ n: UInt32) -> Int32

@_silgen_name("xu_ui_mem_append")
func xu_ui_mem_append(_ name: UnsafePointer<CChar>?, _ body: UnsafePointer<CChar>?, _ add_nl: Int32)

@_silgen_name("xu_ui_mem_clear")
func xu_ui_mem_clear(_ name: UnsafePointer<CChar>?)

@_silgen_name("xu_ui_mem_set_n")
func xu_ui_mem_set_n(_ name: UnsafePointer<CChar>?, _ body: UnsafePointer<CChar>?, _ body_len: UInt32)

@_silgen_name("xu_ui_mem_wait_nonempty")
func xu_ui_mem_wait_nonempty(_ name: UnsafePointer<CChar>?, _ timeout_ms: Int32) -> Int32
@_silgen_name("xu_ui_host_set_kick")
func xu_ui_host_set_kick(_ fn: (@convention(c) () -> Void)?)

func xuPackBytes(_ ptr: UnsafePointer<UInt8>?, _ len: UInt32) -> Data? {
  guard let p = ptr, len > 0 else { return nil }
  return Data(bytes: p, count: Int(len))
}

func xuPackWwwData(_ route: String) -> Data? {
  var len: UInt32 = 0
  let p = route.withCString { xu_pack_www_ptr($0, &len) }
  return xuPackBytes(p, len)
}

func xuPackPathData(_ path: String) -> Data? {
  var len: UInt32 = 0
  let p = path.withCString { xu_pack_path_ptr($0, &len) }
  return xuPackBytes(p, len)
}

func xuPackIconImage() -> NSImage? {
  var len: UInt32 = 0
  guard let data = xuPackBytes(xu_pack_icon_ptr(&len), len) else { return nil }
  return NSImage(data: data)
}

/// Pack/oneexe: in-process mailbox (aligned with Windows xu_ui_mem). Disk only if real TMP.
func xuUiMemOnlyTmp(_ tmp: String) -> Bool {
  tmp.isEmpty || tmp == ":xu:" || tmp == ":mem:"
}

func xuUiWriteSlot(_ name: String, _ body: String) {
  name.withCString { n in
    body.withCString { b in xu_ui_mem_set(n, b) }
  }
}

func xuUiAppendSlot(_ name: String, _ body: String, addNl: Bool = true) {
  name.withCString { n in
    body.withCString { b in xu_ui_mem_append(n, b, addNl ? 1 : 0) }
  }
}

func xuUiClearSlot(_ name: String) {
  name.withCString { xu_ui_mem_clear($0) }
}

func xuUiReadSlot(_ name: String, cap: Int = 65536) -> String? {
  var buf = [CChar](repeating: 0, count: max(cap, 8))
  let n = name.withCString { xu_ui_mem_get($0, &buf, UInt32(buf.count)) }
  if n < 0 { return nil }
  return String(cString: buf)
}

func xuUiReadSlotTrimmed(_ name: String) -> String {
  (xuUiReadSlot(name) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
}

/// Launch-time read: mem first, then disk if real TMP (aligned with Windows host).
func xuUiLaunchRead(_ tmp: String, _ name: String) -> String {
  if let mem = xuUiReadSlot(name) {
    return mem.trimmingCharacters(in: .whitespacesAndNewlines)
  }
  if xuUiMemOnlyTmp(tmp) { return "" }
  let path = (tmp as NSString).appendingPathComponent(name)
  let raw = (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
  return raw.trimmingCharacters(in: .whitespacesAndNewlines)
}

func xuImageFromPathOrPack(_ raw: String) -> NSImage? {
  let p = raw.trimmingCharacters(in: .whitespacesAndNewlines)
  if p.isEmpty { return xuPackIconImage() }
  if p.hasPrefix("/"), FileManager.default.fileExists(atPath: p),
     let img = NSImage(contentsOfFile: p) {
    return img
  }
  let cwd = FileManager.default.currentDirectoryPath
  let joined = (cwd as NSString).appendingPathComponent(p)
  if FileManager.default.fileExists(atPath: joined),
     let img = NSImage(contentsOfFile: joined) {
    return img
  }
  if let data = xuPackPathData(p), let img = NSImage(data: data) {
    return img
  }
  return xuPackIconImage()
}

// Shell host: App / Window / Menu / Tray / shell.* commands.
// Content backends plug in via XuContentRegistry (e.g. #ui/webview → macos_webview.swift).
// Built into XuUIHost.app so Bundle.main / notifications work.

/// Top strip for dragging frameless windows (WKWebView eats background-drag).
final class DragRegionView: NSView {
  override func mouseDown(with event: NSEvent) {
    window?.performDrag(with: event)
  }

  override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// Forces subviews to fill bounds; optional PNG alpha mask for shaped hit-testing.
final class FillView: NSView {
  weak var host: AppDelegate?
  var maskImage: NSImage?
  var maskBitmap: NSBitmapImageRep?
  /// When true, draw the mask image as the window face (no content plugin chrome).
  var showMaskFace = false

  override var isOpaque: Bool { false }

  override func layout() {
    super.layout()
    let b = bounds
    for v in subviews {
      if v.frame != b {
        v.frame = b
      }
    }
    applyLayerMask()
  }

  override func resizeSubviews(withOldSize oldSize: NSSize) {
    super.resizeSubviews(withOldSize: oldSize)
    let b = bounds
    for v in subviews {
      v.frame = b
    }
    applyLayerMask()
  }

  override func draw(_ dirtyRect: NSRect) {
    if showMaskFace, let img = maskImage {
      NSColor.clear.setFill()
      bounds.fill()
      img.draw(in: bounds, from: .zero, operation: .sourceOver, fraction: 1.0)
      return
    }
    super.draw(dirtyRect)
  }

  override func hitTest(_ point: NSPoint) -> NSView? {
    if let bmp = maskBitmap {
      let alpha = sampleAlpha(at: point, bitmap: bmp)
      if alpha < 0.08 {
        return nil
      }
    }
    return super.hitTest(point)
  }

  func setMask(image: NSImage?) {
    maskImage = image
    maskBitmap = nil
    if let image = image {
      let sz = image.size
      if sz.width > 0, sz.height > 0,
         let rep = NSBitmapImageRep(
           bitmapDataPlanes: nil,
           pixelsWide: Int(sz.width),
           pixelsHigh: Int(sz.height),
           bitsPerSample: 8,
           samplesPerPixel: 4,
           hasAlpha: true,
           isPlanar: false,
           colorSpaceName: .deviceRGB,
           bytesPerRow: 0,
           bitsPerPixel: 0)
      {
        NSGraphicsContext.saveGraphicsState()
        if let ctx = NSGraphicsContext(bitmapImageRep: rep) {
          NSGraphicsContext.current = ctx
          image.draw(
            in: NSRect(origin: .zero, size: sz),
            from: .zero,
            operation: .copy,
            fraction: 1.0)
          ctx.flushGraphics()
        }
        NSGraphicsContext.restoreGraphicsState()
        maskBitmap = rep
      }
    }
    showMaskFace = image != nil && (host?.content == nil)
    applyLayerMask()
    needsDisplay = true
    window?.invalidateShadow()
  }

  func applyLayerMask() {
    wantsLayer = true
    guard let image = maskImage else {
      layer?.mask = nil
      return
    }
    let maskLayer = CALayer()
    maskLayer.frame = bounds
    maskLayer.contents = image
    maskLayer.contentsGravity = .resize
    layer?.mask = maskLayer
  }

  func sampleAlpha(at point: NSPoint, bitmap: NSBitmapImageRep) -> CGFloat {
    let pw = CGFloat(bitmap.pixelsWide)
    let ph = CGFloat(bitmap.pixelsHigh)
    guard bounds.width > 0, bounds.height > 0, pw > 0, ph > 0 else { return 1 }
    let x = Int((point.x / bounds.width) * pw)
    // FillView is not flipped by default (AppKit bottom-left origin).
    let yImg = Int((point.y / bounds.height) * ph)
    let xx = max(0, min(Int(pw) - 1, x))
    let yy = max(0, min(Int(ph) - 1, yImg))
    guard let color = bitmap.colorAt(x: xx, y: Int(ph) - 1 - yy) else { return 1 }
    return color.alphaComponent
  }
}


/// Content plugins (#ui/webview, #ui/draw, native views, …) install into the shell window.
/// Shell never names a concrete backend — plugins register via +registerPlugin bootstrap.
protocol XuContentPlugin: AnyObject {
  func install(into root: NSView, host: AppDelegate)
  func handleCmd(_ s: String) -> Bool
  func onPoll()
  func syncFrame()
  func evalJS(_ js: String)
  func snapshotPNG(to path: String, completion: @escaping (Bool) -> Void)
  func snapshotClipboard(completion: @escaping (Bool) -> Void)
  func onFilesDropped(_ paths: [String])
  /// Optional chrome (e.g. WebView DevTools). Draw/native typically false.
  var wantsDevToolsMenu: Bool { get }
}

enum XuContentRegistry {
  /// Set by a linked content plugin's +registerPlugin (nil = shell-only / empty slot).
  static var make: ((AppDelegate) -> XuContentPlugin)?
}

/// Draw icon + badge ourselves. System `badgeLabel` is often a no-op on macOS 26
/// (no Notification Settings row, ad-hoc sign, custom applicationIconImage).
final class DockIconBadgeView: NSView {
  var icon: NSImage?
  var badge: String = "" {
    didSet { needsDisplay = true }
  }

  override var isFlipped: Bool { true }

  override func draw(_ dirtyRect: NSRect) {
    let b = bounds
    let clip = NSBezierPath(roundedRect: b, xRadius: b.width * 0.22, yRadius: b.height * 0.22)
    clip.addClip()
    if let icon {
      icon.draw(
        in: b,
        from: .zero,
        operation: .sourceOver,
        fraction: 1,
        respectFlipped: true,
        hints: [.interpolation: NSImageInterpolation.high])
    } else {
      NSColor.windowBackgroundColor.setFill()
      b.fill()
    }
    let label = badge.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !label.isEmpty else { return }
    let fontSize = max(11, b.width * 0.26)
    let attrs: [NSAttributedString.Key: Any] = [
      .font: NSFont.boldSystemFont(ofSize: fontSize),
      .foregroundColor: NSColor.white
    ]
    let text = NSAttributedString(string: label, attributes: attrs)
    let ts = text.size()
    let padX = max(5, b.width * 0.07)
    let padY = max(2, b.height * 0.035)
    let bh = ts.height + padY * 2
    let bw = max(bh, ts.width + padX * 2)
    let inset = max(2, b.width * 0.03)
    let badgeRect = NSRect(x: b.maxX - bw - inset, y: inset, width: bw, height: bh)
    let path = NSBezierPath(roundedRect: badgeRect, xRadius: bh / 2, yRadius: bh / 2)
    NSColor.systemRed.setFill()
    path.fill()
    NSColor.white.setStroke()
    path.lineWidth = max(1.2, b.width * 0.02)
    path.stroke()
    let origin = NSPoint(
      x: badgeRect.midX - ts.width / 2,
      y: badgeRect.midY - ts.height / 2)
    text.draw(at: origin)
  }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuItemValidation {

  /// Weak shared for mailbox → UI-thread kick (shell cmd latency).
  static weak var sharedKick: AppDelegate?

  let window: NSWindow
  let tmp: String
  let port: String
  weak var rootView: NSView?
  var content: XuContentPlugin?
  var statusItem: NSStatusItem?
  var pollTimer: Timer?
  var lastTitle: String = ""
  var notifiedClose = false
  var notifiedExit = false
  var resizeWork: DispatchWorkItem?
  var moveWork: DispatchWorkItem?
  var lastSizeKey: String = ""
  /// Last size applied from xu_ui_size.txt — must not track live resize (or drainSize snaps back).
  var lastSizeFileKey: String = ""
  /// True while window is orderOut'd via hide — must not quit the app.
  var hiddenByCmd = false
  var isFloating = false
  var bounceClearWork: DispatchWorkItem?
  var toastPanel: NSPanel?
  var closeGuard = false
  var closePending = false
  var isFrameless = false
  var isTransparent = false
  var savedStyleMask: NSWindow.StyleMask = [.titled, .closable, .miniaturizable, .resizable]
  var dragBar: DragRegionView?
  var dockTileView: DockIconBadgeView?

  init(window: NSWindow, tmp: String, port: String) {
    self.window = window
    self.tmp = tmp
    self.port = port
    super.init()
    AppDelegate.sharedKick = self
    xu_ui_host_set_kick {
      // Coalesce: one drain per turn of the main runloop.
      DispatchQueue.main.async {
        guard let d = AppDelegate.sharedKick else { return }
        d.drainTitle()
        d.drainSize()
        d.drainCmds()
        d.drainCloseGuardFlag()
      }
    }
  }

  /// Invoke +registerPlugin on each ObjC class listed in xu_ui_plugin_bootstrap.txt.
  /// Class names come from ui.register_content_plugin(..., bootstrap) — not hardcoded.
  func loadRegisteredContentBootstraps() {
    let raw = readSlotRaw("xu_ui_plugin_bootstrap.txt")
    for line in raw.split(separator: "\n") {
      let name = String(line).trimmingCharacters(in: .whitespacesAndNewlines)
      if name.isEmpty { continue }
      if let cls = NSClassFromString(name) as? NSObject.Type {
        cls.perform(NSSelectorFromString("registerPlugin"))
      }
    }
  }

  func applicationDidFinishLaunching(_ notification: Notification) {
    window.delegate = self
    // Load whatever bootstrap class names Xu registered (webview / draw / native / …).
    loadRegisteredContentBootstraps()
    if let root = rootView, let make = XuContentRegistry.make {
      let plugin = make(self)
      content = plugin
      plugin.install(into: root, host: self)
    }
    // Apply chrome flags written before App.run() so the first paint has no titlebar.
    applyLaunchChrome()
    // No content plugin: leave FillView empty (shaped mask draws the face).
    applyAppIcon()
    buildMenu()
    buildTray()
    window.center()
    window.makeKeyAndOrderFront(nil)
    NSApp.activate(ignoringOtherApps: true)
    lastTitle = window.title
    let s = window.frame.size
    lastSizeKey = "\(Int(s.width)) \(Int(s.height))"
    lastSizeFileKey = readTrimmed("xu_ui_size.txt")
    if lastSizeFileKey.isEmpty {
      lastSizeFileKey = lastSizeKey
    }
    appendShellFile("ready")
    pollTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
      self?.content?.syncFrame()
      self?.content?.onPoll()
      self?.drainTitle()
      self?.drainSize()
      self?.drainCmds()
      self?.drainCloseGuardFlag()
    }
  }

  func drainCloseGuardFlag() {
    let v = readTrimmed("xu_ui_close_guard.txt")
    if v == "1" {
      closeGuard = true
    } else if v == "0" {
      closeGuard = false
    }
  }

  func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

  func applicationWillTerminate(_ notification: Notification) {
    notifyShell(payload: "exit")
  }

  func windowShouldClose(_ sender: NSWindow) -> Bool {
    if notifiedExit { return true }
    if closeGuard {
      promptCloseConfirm()
      return false
    }
    performQuitFromClose()
    return true
  }

  func performQuitFromClose() {
    hiddenByCmd = false
    closePending = false
    notifyShell(payload: "closed")
    DispatchQueue.main.async { [weak self] in
      self?.notifyShell(payload: "exit")
      NSApp.terminate(nil)
    }
  }

  func promptCloseConfirm() {
    if closePending { return }
    closePending = true
    appendShellFile("close_requested")
    let alert = NSAlert()
    alert.messageText = "Quit Xu?"
    alert.informativeText = "Close guard is on. Quit the application?"
    alert.alertStyle = .warning
    alert.addButton(withTitle: "Quit")
    alert.addButton(withTitle: "Cancel")
    let resp = alert.runModal()
    if resp == .alertFirstButtonReturn {
      acceptClose()
    } else {
      rejectClose()
    }
  }

  func acceptClose() {
    closeGuard = false
    try? "0".write(
      toFile: (tmp as NSString).appendingPathComponent("xu_ui_close_guard.txt"),
      atomically: true,
      encoding: .utf8)
    closePending = false
    performQuitFromClose()
  }

  func rejectClose() {
    closePending = false
    appendShellFile("close_rejected")
  }

  @objc func onMenu(_ sender: NSMenuItem) {
    let id = sender.representedObject as? String ?? sender.title
    if id == "quit" {
      if closeGuard {
        promptCloseConfirm()
        return
      }
      notifyShell(payload: "exit")
      NSApp.terminate(nil)
      return
    }
    postInvoke(name: "menu", payload: id)
  }

  func windowDidBecomeKey(_ notification: Notification) {
    appendShellFile("focused")
  }

  func windowDidResignKey(_ notification: Notification) {
    appendShellFile("blurred")
  }

  func windowDidResize(_ notification: Notification) {
    content?.syncFrame()
    resizeWork?.cancel()
    let work = DispatchWorkItem { [weak self] in
      guard let self = self else { return }
      self.content?.syncFrame()
      let s = self.window.frame.size
      let key = "\(Int(s.width)) \(Int(s.height))"
      self.lastSizeKey = key
      self.appendShellFile("resized\t\(Int(s.width))\t\(Int(s.height))")
    }
    resizeWork = work
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: work)
  }

  func windowDidEndLiveResize(_ notification: Notification) {
    content?.syncFrame()
    let s = window.frame.size
    let key = "\(Int(s.width)) \(Int(s.height))"
    lastSizeKey = key
    lastSizeFileKey = key
    writeSlot("xu_ui_size.txt", key)
  }

  func windowDidEnterFullScreen(_ notification: Notification) {
    content?.syncFrame()
  }

  func windowDidExitFullScreen(_ notification: Notification) {
    content?.syncFrame()
  }

  func windowDidZoom(_ notification: Notification) {
    content?.syncFrame()
  }

  func windowDidMove(_ notification: Notification) {
    moveWork?.cancel()
    let work = DispatchWorkItem { [weak self] in
      guard let self = self else { return }
      let o = self.window.frame.origin
      self.appendShellFile("moved\t\(Int(o.x))\t\(Int(o.y))")
    }
    moveWork = work
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: work)
  }

  func validateMenuItem(_ menuItem: NSMenuItem) -> Bool { true }

  @objc func onTray(_ sender: NSMenuItem) {
    let id = sender.representedObject as? String ?? sender.title
    if id == "quit" {
      if closeGuard {
        promptCloseConfirm()
        return
      }
      notifyShell(payload: "exit")
      NSApp.terminate(nil)
      return
    }
    if id == "show" {
      bringToFront()
    }
    if id == "hide" {
      hideWindow()
    }
    postInvoke(name: "tray", payload: id)
  }

  func bringToFront() {
    hiddenByCmd = false
    window.makeKeyAndOrderFront(nil)
    NSApp.activate(ignoringOtherApps: true)
  }

  func hideWindow() {
    hiddenByCmd = true
    window.orderOut(nil)
  }

  func notifyShell(payload: String) {
    if payload == "closed" {
      if notifiedClose { return }
      notifiedClose = true
    }
    if payload == "exit" {
      if notifiedExit { return }
      notifiedExit = true
    }
    // File only for lifecycle — HTTP + file both fire → duplicate events on Xu.
    appendShellFile(payload)
  }

  func appendShellFile(_ payload: String) {
    xuUiAppendSlot("xu_ui_shell_event.txt", payload, addNl: true)
    if xuUiMemOnlyTmp(tmp) { return }
    let path = (tmp as NSString).appendingPathComponent("xu_ui_shell_event.txt")
    let line = payload + "\n"
    if FileManager.default.fileExists(atPath: path),
       let handle = FileHandle(forWritingAtPath: path) {
      defer { try? handle.close() }
      handle.seekToEndOfFile()
      if let data = line.data(using: .utf8) {
        handle.write(data)
      }
    } else {
      try? line.write(toFile: path, atomically: true, encoding: .utf8)
    }
  }

  func postInvoke(name: String, payload: String) {
    guard let url = URL(string: "http://127.0.0.1:\(port)/__xu/invoke") else { return }
    var req = URLRequest(url: url)
    req.httpMethod = "POST"
    req.httpBody = "\(name)\n\(payload)".data(using: .utf8)
    URLSession.shared.dataTask(with: req).resume()
  }

  func drainTitle() {
    let t = readTrimmed("xu_ui_title.txt")
    if t.isEmpty || t == lastTitle { return }
    lastTitle = t
    window.title = t
  }

  func drainSize() {
    // Do not fight user zoom / fullscreen with the last scripted size.
    if window.styleMask.contains(.fullScreen) || window.isZoomed { return }
    let t = readTrimmed("xu_ui_size.txt")
    // Compare to last *file* apply — not live window size (user drag updates lastSizeKey).
    if t.isEmpty || t == lastSizeFileKey { return }
    let parts = t.split(separator: " ")
    guard parts.count >= 2,
          let w = Double(parts[0]),
          let h = Double(parts[1]),
          w > 0, h > 0 else { return }
    lastSizeFileKey = t
    lastSizeKey = t
    var f = window.frame
    f.size = NSSize(width: w, height: h)
    window.setFrame(f, display: true)
    content?.syncFrame()
  }

  func writeState() {
    let vis = (!hiddenByCmd && window.isVisible) ? "1" : "0"
    let zoomed = window.isZoomed ? "1" : "0"
    let full = window.styleMask.contains(.fullScreen) ? "1" : "0"
    let floating = isFloating ? "1" : "0"
    let guardOn = closeGuard ? "1" : "0"
    let line = "visible=\(vis) zoomed=\(zoomed) fullscreen=\(full) floating=\(floating) close_guard=\(guardOn)"
    writeSlot("xu_ui_state.txt", line)
    appendShellFile("state\t\(line)")
  }

  func writeBounds() {
    let f = window.frame
    let line = "\(Int(f.origin.x)) \(Int(f.origin.y)) \(Int(f.size.width)) \(Int(f.size.height))"
    writeSlot("xu_ui_bounds.txt", line)
    appendShellFile("bounds\t\(line)")
  }

  func bounceDock() {
    // requestUserAttention is a no-op while the app is active — always badge the Dock,
    // and when inactive also bounce; when active flash the title for visible feedback.
    bounceClearWork?.cancel()
    applyDockBadgeLabel("!")
    _ = NSApp.requestUserAttention(.criticalRequest)
    if NSApp.isActive {
      if !window.title.hasPrefix("[!] ") {
        window.title = "[!] " + window.title
      }
    }
    let work = DispatchWorkItem { [weak self] in
      guard let self = self else { return }
      self.applyDockBadgeLabel("")
      if self.window.title.hasPrefix("[!] ") {
        self.window.title = String(self.window.title.dropFirst(4))
      }
    }
    bounceClearWork = work
    DispatchQueue.main.asyncAfter(deadline: .now() + 2.0, execute: work)
  }

  func pickFile() {
    let panel = NSOpenPanel()
    panel.allowsMultipleSelection = false
    panel.canChooseDirectories = false
    panel.canChooseFiles = true
    panel.begin { [weak self] result in
      guard let self = self else { return }
      if result == .OK, let url = panel.url {
        self.writeSlot("xu_ui_pick.txt", url.path)
        self.appendShellFile("file_picked\t\(url.path)")
      } else {
        self.writeSlot("xu_ui_pick.txt", "")
        self.appendShellFile("file_picked\t")
      }
    }
  }

  func pickFolder() {
    let panel = NSOpenPanel()
    panel.allowsMultipleSelection = false
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.begin { [weak self] result in
      guard let self = self else { return }
      if result == .OK, let url = panel.url {
        self.writeSlot("xu_ui_pick.txt", url.path)
        self.appendShellFile("folder_picked\t\(url.path)")
      } else {
        self.writeSlot("xu_ui_pick.txt", "")
        self.appendShellFile("folder_picked\t")
      }
    }
  }

  func showAlert(confirm: Bool) {
    let title = readTrimmed("xu_ui_alert_title.txt")
    let msg = readSlotRaw("xu_ui_alert_msg.txt")
    let alert = NSAlert()
    alert.messageText = title.isEmpty ? "Xu" : title
    alert.informativeText = msg
    if confirm {
      alert.alertStyle = .warning
      alert.addButton(withTitle: "OK")
      alert.addButton(withTitle: "Cancel")
    } else {
      alert.alertStyle = .informational
      alert.addButton(withTitle: "OK")
    }
    let resp = alert.runModal()
    if confirm {
      let ok = resp == .alertFirstButtonReturn ? "1" : "0"
      writeSlot("xu_ui_alert_result.txt", ok)
      appendShellFile("confirm\t\(ok)")
    } else {
      writeSlot("xu_ui_alert_result.txt", "ok")
      appendShellFile("alert\tok")
    }
  }

  func hasRealAppBundle() -> Bool {
    guard let bid = Bundle.main.bundleIdentifier, !bid.isEmpty else { return false }
    return Bundle.main.bundlePath.hasSuffix(".app")
  }

  func showNotify() {
    let title = readTrimmed("xu_ui_notify_title.txt")
    let body = readSlotRaw("xu_ui_notify_body.txt")
    bounceDock()
    if hasRealAppBundle() {
      deliverSystemNotify(title: title.isEmpty ? "Xu" : title, body: body)
    } else {
      showToastNotify(title: title.isEmpty ? "Xu" : title, body: body)
    }
    appendShellFile("notify\tok")
  }

  func deliverSystemNotify(title: String, body: String) {
    let center = UNUserNotificationCenter.current()
    center.requestAuthorization(options: [.alert, .sound, .badge]) { [weak self] granted, _ in
      guard let self = self else { return }
      let content = UNMutableNotificationContent()
      content.title = title
      content.body = body
      content.sound = .default
      let req = UNNotificationRequest(
        identifier: "xu-\(UUID().uuidString)",
        content: content,
        trigger: nil)
      center.add(req) { [weak self] err in
        if err != nil || !granted {
          DispatchQueue.main.async {
            self?.showToastNotify(title: title, body: body)
          }
        } else {
          DispatchQueue.main.async {
            self?.content?.evalJS(
              "var el=document.getElementById('out');if(el)el.textContent='notify: system';")
          }
        }
      }
    }
  }

  func showToastNotify(title: String, body: String) {
    // Fallback when not a real .app or notification permission denied.
    toastPanel?.orderOut(nil)
    let panel = NSPanel(
      contentRect: NSRect(x: 0, y: 0, width: 340, height: 88),
      styleMask: [.titled, .nonactivatingPanel, .fullSizeContentView],
      backing: .buffered,
      defer: false)
    panel.isFloatingPanel = true
    panel.level = .statusBar
    panel.hidesOnDeactivate = false
    panel.isReleasedWhenClosed = false
    panel.titlebarAppearsTransparent = true
    panel.titleVisibility = .hidden
    panel.backgroundColor = NSColor(calibratedWhite: 0.12, alpha: 0.96)
    let titleField = NSTextField(labelWithString: title)
    titleField.font = NSFont.boldSystemFont(ofSize: 13)
    titleField.textColor = .white
    titleField.frame = NSRect(x: 16, y: 48, width: 308, height: 20)
    let bodyField = NSTextField(wrappingLabelWithString: body)
    bodyField.font = NSFont.systemFont(ofSize: 12)
    bodyField.textColor = NSColor(calibratedWhite: 0.85, alpha: 1)
    bodyField.frame = NSRect(x: 16, y: 12, width: 308, height: 36)
    panel.contentView?.addSubview(titleField)
    panel.contentView?.addSubview(bodyField)
    if let screen = window.screen ?? NSScreen.main {
      let vf = screen.visibleFrame
      let x = vf.maxX - 360
      let y = vf.maxY - 120
      panel.setFrameOrigin(NSPoint(x: x, y: y))
    } else {
      panel.center()
    }
    panel.orderFront(nil)
    toastPanel = panel
    DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self, weak panel] in
      panel?.orderOut(nil)
      if self?.toastPanel === panel {
        self?.toastPanel = nil
      }
    }
    content?.evalJS(
      "var el=document.getElementById('out');if(el)el.textContent='notify: toast';")
  }

  func saveFile() {
    let panel = NSSavePanel()
    let suggested = readTrimmed("xu_ui_save_name.txt")
    panel.nameFieldStringValue = suggested.isEmpty ? "untitled.txt" : suggested
    panel.begin { [weak self] result in
      guard let self = self else { return }
      if result == .OK, let url = panel.url {
        self.writeSlot("xu_ui_save.txt", url.path)
        self.appendShellFile("file_saved\t\(url.path)")
      } else {
        self.writeSlot("xu_ui_save.txt", "")
        self.appendShellFile("file_saved\t")
      }
    }
  }

  func currentDockIcon() -> NSImage? {
    if let img = NSApp.applicationIconImage { return img }
    if let img = loadIcon(namedFile: "xu_ui_app_icon.txt") { return img }
    if let img = xuPackIconImage() { return img }
    let path = Bundle.main.bundlePath
    if path.hasSuffix(".app") {
      return NSWorkspace.shared.icon(forFile: path)
    }
    return NSImage(named: NSImage.applicationIconName)
  }

  func installDockTileView() {
    if dockTileView != nil { return }
    guard let icon = currentDockIcon() else { return }
    let v = DockIconBadgeView(frame: NSRect(x: 0, y: 0, width: 128, height: 128))
    v.autoresizingMask = [.width, .height]
    v.icon = icon
    dockTileView = v
    NSApp.dockTile.contentView = v
    NSApp.dockTile.display()
  }

  func applyDockBadgeLabel(_ text: String) {
    let label = text.trimmingCharacters(in: .whitespacesAndNewlines)
    if label.isEmpty {
      dockTileView?.badge = ""
      NSApp.dockTile.contentView = nil
      dockTileView = nil
      NSApp.dockTile.badgeLabel = nil
      NSApp.dockTile.display()
      return
    }
    installDockTileView()
    if let v = dockTileView {
      v.badge = label
      v.needsDisplay = true
      NSApp.dockTile.display()
      return
    }
    NSApp.dockTile.badgeLabel = label
    NSApp.dockTile.display()
  }

  func setDockBadge(_ label: String) {
    let text = label.trimmingCharacters(in: .whitespacesAndNewlines)
    bounceClearWork?.cancel()
    applyDockBadgeLabel(text)
    if text.isEmpty {
      content?.evalJS(
        "var el=document.getElementById('out');if(el)el.textContent='dock badge: (cleared)';")
    } else {
      let safe = text
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "'", with: "\\'")
      content?.evalJS(
        "var el=document.getElementById('out');if(el)el.textContent='dock badge: \(safe)';")
    }
  }

  func applyAppearance(_ name: String) {
    let n = name.lowercased()
    if n == "dark" {
      NSApp.appearance = NSAppearance(named: .darkAqua)
      window.appearance = NSAppearance(named: .darkAqua)
    } else if n == "light" {
      NSApp.appearance = NSAppearance(named: .aqua)
      window.appearance = NSAppearance(named: .aqua)
    } else {
      NSApp.appearance = nil
      window.appearance = nil
    }
    content?.evalJS(
      "var el=document.getElementById('out');if(el)el.textContent='appearance: \(n)';")
  }

  func takeScreenshotToClipboard() {
    content?.snapshotClipboard { [weak self] ok in
      guard let self = self else { return }
      if ok {
        self.appendShellFile("screenshot\tclipboard")
        self.content?.evalJS("var el=document.getElementById('out');if(el)el.textContent='screenshot → clipboard';")
      } else {
        self.appendShellFile("screenshot\t")
      }
    }
  }

  func takeScreenshot() {
    // Pack/oneexe uses mem mailbox (tmp empty) — PNG must still land on a real path.
    let dir = xuUiMemOnlyTmp(tmp)
      ? FileManager.default.temporaryDirectory.path
      : tmp
    let out = (dir as NSString).appendingPathComponent("xu_ui_shot.png")
    guard let content = content else {
      appendShellFile("screenshot\t")
      return
    }
    content.snapshotPNG(to: out) { [weak self] ok in
      guard let self = self else { return }
      if ok {
        self.appendShellFile("screenshot\t\(out)")
      } else {
        self.appendShellFile("screenshot\t")
      }
    }
  }

  func readTrimmed(_ name: String) -> String {
    if let mem = xuUiReadSlot(name) {
      return mem.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    if xuUiMemOnlyTmp(tmp) { return "" }
    let path = (tmp as NSString).appendingPathComponent(name)
    let raw = (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
    return raw.trimmingCharacters(in: .whitespacesAndNewlines)
  }

  func writeSlot(_ name: String, _ body: String) {
    xuUiWriteSlot(name, body)
    if xuUiMemOnlyTmp(tmp) { return }
    let path = (tmp as NSString).appendingPathComponent(name)
    try? body.write(toFile: path, atomically: true, encoding: .utf8)
  }

  func readSlotRaw(_ name: String) -> String {
    if let mem = xuUiReadSlot(name) { return mem }
    if xuUiMemOnlyTmp(tmp) { return "" }
    let path = (tmp as NSString).appendingPathComponent(name)
    return (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
  }

  @_silgen_name("xu_ui_invoke_sync")
  func xu_ui_invoke_sync(_ req: UnsafePointer<CChar>?) -> UnsafeMutablePointer<CChar>?

  /// Scheme invoke: direct sync call into Xu worker (no req/resp slot files).
  func xuIpcInvoke(_ body: String) -> String {
    let raw: UnsafeMutablePointer<CChar>? = body.withCString { xu_ui_invoke_sync($0) }
    guard let raw else {
      return "ok: false\nerror: !s invoke null\n"
    }
    defer { free(raw) }
    return String(cString: raw)
  }

  /// Invoke off the main thread; complete as soon as Xu replies.
  /// Do NOT wait for main-queue drainCmds — that delayed the JS Promise by
  /// however long the main runloop was busy (often ~1–2s under timer/eval load).
  func xuIpcInvokeAsync(_ body: String, completion: @escaping (String) -> Void) {
    Self.ipcInvokeQueue.async { [weak self] in
      guard let self = self else {
        completion("ok: false\nerror: !s invoke host gone\n")
        return
      }
      let t0 = CFAbsoluteTimeGetCurrent()
      let resp = self.xuIpcInvoke(body)
      let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000.0
      if ProcessInfo.processInfo.environment["XU_UI_TIMING"] == "1" {
        fputs(String(format: "xu_ui_timing invoke_sync=%.1fms\n", ms), stderr)
      }
      completion(resp)
      DispatchQueue.main.async {
        self.drainCmds()
        self.drainTitle()
        self.drainSize()
      }
    }
  }

  private static let ipcInvokeQueue = DispatchQueue(
    label: "dev.xu.ui.ipc.invoke",
    qos: .userInteractive
  )

  /// Pop one XUN emit record from xu_ui_emit_q.txt (RS 0x1e separated).
  func xuIpcPoll() -> String {
    let raw = readSlotRaw("xu_ui_emit_q.txt")
    if raw.isEmpty { return "" }
    let rs = "\u{001e}"
    if let idx = raw.firstIndex(of: Character(rs)) {
      let msg = String(raw[..<idx])
      let rest = String(raw[raw.index(after: idx)...])
      writeSlot("xu_ui_emit_q.txt", rest)
      return msg
    }
    writeSlot("xu_ui_emit_q.txt", "")
    return raw
  }

  func readLines(slot name: String) -> [(String, String)] {
    let raw = readSlotRaw(name)
    var out: [(String, String)] = []
    for line in raw.split(separator: "\n") {
      let s = String(line)
      if s.isEmpty { continue }
      if let tab = s.firstIndex(of: "\t") {
        out.append((String(s[..<tab]), String(s[s.index(after: tab)...])))
      } else {
        out.append((s, s))
      }
    }
    return out
  }

  func readLines(_ path: String) -> [(String, String)] {
    // Legacy full-path API — prefer slot name when path ends with xu_ui_*.txt
    let base = (path as NSString).lastPathComponent
    if base.hasPrefix("xu_ui_") {
      return readLines(slot: base)
    }
    guard let raw = try? String(contentsOfFile: path, encoding: .utf8) else { return [] }
    var out: [(String, String)] = []
    for line in raw.split(separator: "\n") {
      let s = String(line)
      if s.isEmpty { continue }
      if let tab = s.firstIndex(of: "\t") {
        out.append((String(s[..<tab]), String(s[s.index(after: tab)...])))
      } else {
        out.append((s, s))
      }
    }
    return out
  }

  func resolveIconPath(_ raw: String) -> String? {
    let p = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    if p.isEmpty { return nil }
    if p.hasPrefix("/") {
      return FileManager.default.fileExists(atPath: p) ? p : nil
    }
    let cwd = FileManager.default.currentDirectoryPath
    let joined = (cwd as NSString).appendingPathComponent(p)
    if FileManager.default.fileExists(atPath: joined) { return joined }
    return nil
  }

  func loadIcon(namedFile file: String) -> NSImage? {
    let trimmed = readTrimmed(file)
    if let img = xuImageFromPathOrPack(trimmed) { return img }
    return xuPackIconImage()
  }

  func applyAppIcon() {
    if let img = loadIcon(namedFile: "xu_ui_app_icon.txt") {
      NSApp.applicationIconImage = img
    }
    if let img = currentDockIcon() {
      dockTileView?.icon = img
      dockTileView?.needsDisplay = true
      if dockTileView != nil {
        NSApp.dockTile.display()
      }
    }
  }

  func buildMenu() {
    let items = readLines(slot: "xu_ui_menu.txt")
    let menubar = NSMenu()
    let appMenu = NSMenu(title: "Xu")
    let appItem = NSMenuItem(title: "Xu", action: nil, keyEquivalent: "")
    appItem.submenu = appMenu
    menubar.addItem(appItem)
    if items.isEmpty {
      let about = NSMenuItem(title: "About", action: #selector(onMenu(_:)), keyEquivalent: "")
      about.target = self
      about.representedObject = "about"
      appMenu.addItem(about)
      appMenu.addItem(NSMenuItem.separator())
      let quit = NSMenuItem(title: "Quit", action: #selector(onMenu(_:)), keyEquivalent: "q")
      quit.target = self
      quit.representedObject = "quit"
      appMenu.addItem(quit)
    } else {
      for (id, label) in items {
        let mi = NSMenuItem(title: label, action: #selector(onMenu(_:)), keyEquivalent: id == "quit" ? "q" : "")
        mi.target = self
        mi.representedObject = id
        appMenu.addItem(mi)
      }
    }
    let editMenu = NSMenu(title: "Edit")
    let editItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
    editItem.submenu = editMenu
    editMenu.addItem(NSMenuItem(title: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x"))
    editMenu.addItem(NSMenuItem(title: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c"))
    editMenu.addItem(NSMenuItem(title: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v"))
    editMenu.addItem(NSMenuItem.separator())
    editMenu.addItem(NSMenuItem(title: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a"))
    menubar.addItem(editItem)
    if content?.wantsDevToolsMenu == true {
      let viewMenu = NSMenu(title: "View")
      let viewItem = NSMenuItem(title: "View", action: nil, keyEquivalent: "")
      viewItem.submenu = viewMenu
      let dt = NSMenuItem(title: "Developer Tools", action: #selector(onDevToolsMenu(_:)), keyEquivalent: "i")
      dt.keyEquivalentModifierMask = [.command, .option]
      dt.target = self
      viewMenu.addItem(dt)
      menubar.addItem(viewItem)
    }
    NSApp.mainMenu = menubar
  }

  @objc func onDevToolsMenu(_ sender: Any?) {
    _ = content?.handleCmd("devtools")
  }

  func buildTray() {
    let tipRaw = readTrimmed("xu_ui_tray_tip.txt")
    let tip = tipRaw.isEmpty ? "Xu" : tipRaw
    let items = readLines(slot: "xu_ui_tray.txt")
    if items.isEmpty { return }
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    if let img = loadIcon(namedFile: "xu_ui_tray_icon.txt") {
      img.isTemplate = false
      img.size = NSSize(width: 18, height: 18)
      item.button?.image = img
      item.button?.title = ""
    } else {
      item.button?.title = "Xu"
    }
    item.button?.toolTip = tip
    let menu = NSMenu()
    for (id, label) in items {
      let mi = NSMenuItem(title: label, action: #selector(onTray(_:)), keyEquivalent: "")
      mi.target = self
      mi.representedObject = id
      menu.addItem(mi)
    }
    item.menu = menu
    statusItem = item
  }

  // xu_ui_cmd.txt lines: "shell.*" | "wv.*" | "content.*" | bare legacy names.
  func contentHandleCmd(_ s: String) -> Bool {
    content?.handleCmd(s) ?? false
  }

  func stripCmdPrefix(_ raw: String) -> String {
    if raw.hasPrefix("shell.") { return String(raw.dropFirst(6)) }
    if raw.hasPrefix("content.") { return String(raw.dropFirst(8)) }
    if raw.hasPrefix("wv.") { return String(raw.dropFirst(3)) }
    return raw
  }

  func drainCmds() {
    let raw = readSlotRaw("xu_ui_cmd.txt")
    if raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return }
    writeSlot("xu_ui_cmd.txt", "")
    for line in raw.split(separator: "\n") {
      let trimmed = String(line).trimmingCharacters(in: .whitespacesAndNewlines)
      if trimmed.isEmpty { continue }
      let toContent = trimmed.hasPrefix("wv.") || trimmed.hasPrefix("content.")
      let s = stripCmdPrefix(trimmed)
      if toContent {
        _ = contentHandleCmd(s)
        continue
      }
      if handleShellCmd(s) {
        continue
      }
      // Legacy unprefixed: try content after shell.
      _ = contentHandleCmd(s)
    }
  }

  /// Returns true if handled as a shell/window command.
  @discardableResult
  func handleShellCmd(_ s: String) -> Bool {
    if s == "show" {
      bringToFront()
      return true
    }
    if s == "hide" {
      hideWindow()
      return true
    }
    if s == "minimize" {
      window.miniaturize(nil)
      return true
    }
    if s == "maximize" {
      if !window.isZoomed { window.zoom(nil) }
      return true
    }
    if s == "unmaximize" {
      if window.isZoomed { window.zoom(nil) }
      return true
    }
    if s == "bounce" {
      bounceDock()
      return true
    }
    if s == "pick_file" {
      pickFile()
      return true
    }
    if s == "pick_folder" {
      pickFolder()
      return true
    }
    if s == "save_file" {
      saveFile()
      return true
    }
    if s == "screenshot" {
      takeScreenshot()
      return true
    }
    if s == "alert" {
      showAlert(confirm: false)
      return true
    }
    if s == "confirm" {
      showAlert(confirm: true)
      return true
    }
    if s == "notify" {
      showNotify()
      return true
    }
    if s == "accept_close" {
      acceptClose()
      return true
    }
    if s == "reject_close" {
      rejectClose()
      return true
    }
    if s.hasPrefix("close_guard\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        closeGuard = parts[1] != "0"
        let flag = closeGuard ? "1" : "0"
        try? flag.write(
          toFile: (tmp as NSString).appendingPathComponent("xu_ui_close_guard.txt"),
          atomically: true,
          encoding: .utf8)
      }
      return true
    }
    if s.hasPrefix("shadow\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        window.hasShadow = parts[1] != "0"
      }
      return true
    }
    if s == "get_state" {
      writeState()
      return true
    }
    if s == "open_path" {
      let p = readTrimmed("xu_ui_path.txt")
      if !p.isEmpty {
        NSWorkspace.shared.open(URL(fileURLWithPath: p))
      }
      return true
    }
    if s == "reveal_path" {
      let p = readTrimmed("xu_ui_path.txt")
      if !p.isEmpty {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: p)])
      }
      return true
    }
    if s.hasPrefix("appearance\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        applyAppearance(String(parts[1]))
      }
      return true
    }
    if s == "dock_badge" || s == "dock_badge_clear" || s.hasPrefix("dock_badge\t") {
      var label = ""
      if s.hasPrefix("dock_badge\t") {
        label = String(s.dropFirst("dock_badge\t".count))
      }
      setDockBadge(label)
      return true
    }
    if s == "screenshot_clipboard" {
      takeScreenshotToClipboard()
      return true
    }
    if s.hasPrefix("all_spaces\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        if parts[1] != "0" {
          window.collectionBehavior.insert(.canJoinAllSpaces)
        } else {
          window.collectionBehavior.remove(.canJoinAllSpaces)
        }
      }
      return true
    }
    if s == "get_bounds" {
      writeBounds()
      return true
    }
    if s.hasPrefix("titlebar\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        let on = parts[1] != "0"
        if on {
          window.titleVisibility = .visible
          window.titlebarAppearsTransparent = false
          window.styleMask.remove(.fullSizeContentView)
        } else {
          window.titleVisibility = .hidden
          window.titlebarAppearsTransparent = true
          window.styleMask.insert(.fullSizeContentView)
        }
        content?.syncFrame()
      }
      return true
    }
    if s == "fullscreen" {
      if !window.styleMask.contains(.fullScreen) {
        window.toggleFullScreen(nil)
      }
      return true
    }
    if s == "fullscreen_exit" {
      if window.styleMask.contains(.fullScreen) {
        window.toggleFullScreen(nil)
      }
      return true
    }
    if s == "float" {
      isFloating = true
      window.level = .floating
      return true
    }
    if s == "unfloat" {
      isFloating = false
      window.level = .normal
      return true
    }
    if s == "center" {
      window.center()
      return true
    }
    if s.hasPrefix("opacity\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2, let o = Double(parts[1]) {
        let clamped = min(1.0, max(0.15, o))
        window.alphaValue = CGFloat(clamped)
      }
      return true
    }
    if s.hasPrefix("minsize\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 3, let w = Double(parts[1]), let h = Double(parts[2]), w > 0, h > 0 {
        window.minSize = NSSize(width: w, height: h)
      }
      return true
    }
    if s.hasPrefix("resizable\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        let on = parts[1] != "0"
        if on {
          window.styleMask.insert(.resizable)
        } else {
          window.styleMask.remove(.resizable)
        }
      }
      return true
    }
    if s == "open_external" {
      let u = readTrimmed("xu_ui_open_url.txt")
      if let url = URL(string: u), !u.isEmpty {
        NSWorkspace.shared.open(url)
      }
      return true
    }
    if s == "clipboard_set" {
      let text = readSlotRaw("xu_ui_clipboard_set.txt")
      NSPasteboard.general.clearContents()
      NSPasteboard.general.setString(text, forType: .string)
      return true
    }
    if s == "clipboard_get" {
      let text = NSPasteboard.general.string(forType: .string) ?? ""
      writeSlot("xu_ui_clipboard.txt", text)
      appendShellFile("clipboard\t\(text)")
      return true
    }
    if s.hasPrefix("position\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 3, let x = Double(parts[1]), let y = Double(parts[2]) {
        var f = window.frame
        f.origin = NSPoint(x: x, y: y)
        window.setFrame(f, display: true)
      }
      return true
    }
    if s.hasPrefix("frameless\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        setFrameless(parts[1] != "0")
      }
      return true
    }
    if s.hasPrefix("transparent\t") {
      let parts = s.split(separator: "\t")
      if parts.count >= 2 {
        setTransparent(parts[1] != "0")
      }
      return true
    }
    if s.hasPrefix("mask\t") {
      let parts = s.split(separator: "\t", maxSplits: 1, omittingEmptySubsequences: false)
      if parts.count >= 2 {
        applyWindowMask(path: String(parts[1]))
      }
      return true
    }
    if s == "mask_clear" {
      clearWindowMask()
      return true
    }
    if s == "quit" {
      performQuitFromClose()
      return true
    }
    return false
  }

  func setFrameless(_ on: Bool) {
    isFrameless = on
    if on {
      savedStyleMask = window.styleMask
      // Pure borderless — no titlebar chrome.
      window.styleMask = [.borderless]
      window.titleVisibility = .hidden
      window.titlebarAppearsTransparent = true
      window.isMovableByWindowBackground = true
    } else {
      window.styleMask = savedStyleMask.isEmpty
        ? [.titled, .closable, .miniaturizable, .resizable]
        : savedStyleMask
      window.titleVisibility = .visible
      window.titlebarAppearsTransparent = false
      window.isMovableByWindowBackground = false
    }
    syncDragBar()
    if isTransparent {
      setTransparent(true)
    }
    content?.syncFrame()
    window.invalidateShadow()
  }

  func syncDragBar() {
    guard let root = rootView else { return }
    dragBar?.removeFromSuperview()
    dragBar = nil
    guard isFrameless else { return }
    let h: CGFloat = 28
    let bar = DragRegionView(frame: NSRect(x: 0, y: root.bounds.height - h, width: root.bounds.width, height: h))
    bar.autoresizingMask = [.width, .minYMargin]
    bar.wantsLayer = true
    bar.layer?.backgroundColor = NSColor.clear.cgColor
    root.addSubview(bar, positioned: .above, relativeTo: nil)
    dragBar = bar
  }

  func setTransparent(_ on: Bool) {
    isTransparent = on
    if on {
      window.isOpaque = false
      window.backgroundColor = .clear
      rootView?.wantsLayer = true
      rootView?.layer?.backgroundColor = NSColor.clear.cgColor
    } else {
      window.isOpaque = true
      window.backgroundColor = NSColor.windowBackgroundColor
      rootView?.layer?.backgroundColor = nil
    }
    window.invalidateShadow()
  }

  func applyWindowMask(path: String) {
    let p = path.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !p.isEmpty, let img = xuImageFromPathOrPack(p) else { return }
    if !isFrameless { setFrameless(true) }
    if !isTransparent { setTransparent(true) }
    if let root = rootView as? FillView {
      root.host = self
      root.setMask(image: img)
    }
    window.hasShadow = true
    window.invalidateShadow()
  }

  func clearWindowMask() {
    if let root = rootView as? FillView {
      root.setMask(image: nil)
      root.showMaskFace = false
      root.needsDisplay = true
    }
    window.invalidateShadow()
  }

  /// Read xu_ui_frameless / transparent / mask_path written before host launch.
  func applyLaunchChrome() {
    let frameLess = readTrimmed("xu_ui_frameless.txt") == "1"
    let transparent = readTrimmed("xu_ui_transparent.txt") == "1"
    let maskPath = readTrimmed("xu_ui_mask_path.txt")
    if frameLess { setFrameless(true) }
    if transparent { setTransparent(true) }
    if !maskPath.isEmpty {
      applyWindowMask(path: maskPath)
    }
    syncDragBar()
  }
}

/// Same-process entry for statically linked Xu binaries (overrides weak stub).
/// `tmpDir` is the UI temp directory (title/size/cmd files); empty/`:xu:` → mem mailbox.
@_cdecl("xu_ui_host_run")
public func xu_ui_host_run(_ tmpDir: UnsafePointer<CChar>?) -> Int32 {
  var tmp = tmpDir.map { String(cString: $0) }
    ?? ProcessInfo.processInfo.environment["XU_UI_TMP"]
    ?? ""
  if xuUiMemOnlyTmp(tmp) {
    tmp = ""
  }
  let titleRaw = xuUiLaunchRead(tmp, "xu_ui_title.txt")
  let title = titleRaw.isEmpty ? "Xu" : titleRaw
  let sizeRaw = xuUiLaunchRead(tmp, "xu_ui_size.txt")
  let sizeUse = sizeRaw.isEmpty ? "800 560" : sizeRaw
  let parts = sizeUse.split(separator: " ")
  let width = Double(parts.first.flatMap { Double($0) } ?? 800)
  let height = Double(parts.dropFirst().first.flatMap { Double($0) } ?? 560)
  let portRaw = xuUiLaunchRead(tmp, "xu_ui_ipc_port.txt")
  let port = portRaw.isEmpty ? "19287" : portRaw

  let app = NSApplication.shared
  app.setActivationPolicy(.regular)
  let rect = NSRect(x: 80, y: 80, width: width, height: height)
  let wantFrameless = xuUiLaunchRead(tmp, "xu_ui_frameless.txt") == "1"
  let wantTransparent = xuUiLaunchRead(tmp, "xu_ui_transparent.txt") == "1"
  let style: NSWindow.StyleMask = wantFrameless
    ? [.borderless]
    : [.titled, .closable, .miniaturizable, .resizable]
  let win = NSWindow(contentRect: rect, styleMask: style, backing: .buffered, defer: false)
  win.title = title
  win.isReleasedWhenClosed = false
  if wantFrameless {
    win.titleVisibility = .hidden
    win.titlebarAppearsTransparent = true
    win.isMovableByWindowBackground = true
  }
  if wantTransparent {
    win.isOpaque = false
    win.backgroundColor = .clear
  }
  let root = FillView(frame: NSRect(x: 0, y: 0, width: width, height: height))
  win.contentView = root
  win.contentView?.wantsLayer = true

  let delegate = AppDelegate(window: win, tmp: tmp, port: port)
  delegate.isFrameless = wantFrameless
  delegate.isTransparent = wantTransparent
  root.host = delegate
  delegate.rootView = root
  app.delegate = delegate
  app.run()
  return 0
}

#if !XU_UI_STATIC
@main
enum XuNativeHostMain {
  static func main() {
    _ = xu_ui_host_run(nil)
  }
}
#endif
