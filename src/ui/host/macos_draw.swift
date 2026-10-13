import AppKit

// #ui/draw content plugin (macOS). Linked with macos_host.swift.
// Immediate-mode display list, Love2D / Raylib / Cairo-style.
// Origin top-left (isFlipped). Color "#RRGGBB" or "#RRGGBBAA"; "-" skip; "." = current pen.
//
// Frame: begin / present / draw_clear / bgcolor
// Pen:   color / fill / stroke / width
// CTM:   push / pop / origin / translate\tdx\tdy / rotate\tdeg / scale\tsx\tsy
//        scale is percent (100 = 1x); rotate is degrees, clockwise on this y-down canvas.
// Shapes (explicit color last fields, or short form using the pen):
//   fill_rect / stroke_rect / rect / rect_line
//   round_rect / diamond / line / text
//   circle / circle_line / ellipse / ellipse_line / triangle / triangle_line
//   poly\tfill\tstroke\twidth\tx\ty\t...
//   arc\tcx\tcy\tr\ta0\ta1\t#stroke\twidth
//   prompt\ttitle\tdefault
// Click / prompt / scroll / drag: host appends `click\tx\ty` / `prompt\ttext` /
// `scroll\tdx\tdy` / `drag\tdx\tdy` to the shell event slot;
// `#ui` pumps them onto App.event_ch (`ev_click` / `ev_prompt` / `ev_scroll` / `ev_drag`).

enum DrawOp {
  case fillRect(CGRect, NSColor)
  case strokeRect(CGRect, NSColor, CGFloat)
  case roundRect(CGRect, CGFloat, NSColor?, NSColor?, CGFloat)
  case diamond(CGRect, NSColor?, NSColor?, CGFloat)
  case line(CGPoint, CGPoint, NSColor, CGFloat)
  case text(CGPoint, CGFloat, NSColor, String)
  case oval(CGRect, NSColor?, NSColor?, CGFloat)
  case triangle(CGPoint, CGPoint, CGPoint, NSColor?, NSColor?, CGFloat)
  case poly([CGPoint], NSColor?, NSColor?, CGFloat)
  case arc(CGPoint, CGFloat, CGFloat, CGFloat, NSColor, CGFloat)
  case push
  case pop
  case origin
  case translate(CGFloat, CGFloat)
  case rotate(CGFloat)
  case scale(CGFloat, CGFloat)
}

final class DrawCanvasView: NSView {
  var fillColor: NSColor = NSColor(calibratedWhite: 0.10, alpha: 1)
  var labelText: String = ""
  var ops: [DrawOp] = []
  var onClick: ((Int, Int) -> Void)?
  var onScroll: ((Int, Int) -> Void)?
  var onDrag: ((Int, Int) -> Void)?
  var lastDrag: NSPoint?
  var didPan = false
  var camX: CGFloat = 0
  var camY: CGFloat = 0

  override var isFlipped: Bool { true }
  override var acceptsFirstResponder: Bool { true }
  override var mouseDownCanMoveWindow: Bool { false }

  func panBy(_ dx: CGFloat, _ dy: CGFloat) {
    if dx == 0 && dy == 0 { return }
    camX -= dx
    camY -= dy
    needsDisplay = true
  }

  override func draw(_ dirtyRect: NSRect) {
    fillColor.setFill()
    bounds.fill()
    if ops.isEmpty && !labelText.isEmpty {
      let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 22, weight: .semibold),
        .foregroundColor: NSColor.white,
      ]
      let size = labelText.size(withAttributes: attrs)
      let origin = NSPoint(
        x: (bounds.width - size.width) * 0.5,
        y: (bounds.height - size.height) * 0.5)
      labelText.draw(at: origin, withAttributes: attrs)
      return
    }
    guard let ctx = NSGraphicsContext.current?.cgContext else { return }
    let viewBase = ctx.ctm
    ctx.translateBy(x: -camX, y: -camY)
    for op in ops {
      switch op {
      case .push:
        ctx.saveGState()
      case .pop:
        ctx.restoreGState()
      case .origin:
        ctx.concatenate(ctx.ctm.inverted())
        ctx.concatenate(viewBase)
      case .translate(let dx, let dy):
        ctx.translateBy(x: dx, y: dy)
      case .rotate(let deg):
        ctx.rotate(by: deg * .pi / 180)
      case .scale(let sx, let sy):
        ctx.scaleBy(x: sx, y: sy)
      case .fillRect(let r, let c):
        c.setFill()
        r.fill()
      case .strokeRect(let r, let c, let w):
        c.setStroke()
        let p = NSBezierPath(rect: r)
        p.lineWidth = w
        p.stroke()
      case .roundRect(let r, let rad, let fill, let stroke, let w):
        paintPath(NSBezierPath(roundedRect: r, xRadius: rad, yRadius: rad), fill, stroke, w)
      case .diamond(let r, let fill, let stroke, let w):
        let p = NSBezierPath()
        p.move(to: NSPoint(x: r.midX, y: r.minY))
        p.line(to: NSPoint(x: r.maxX, y: r.midY))
        p.line(to: NSPoint(x: r.midX, y: r.maxY))
        p.line(to: NSPoint(x: r.minX, y: r.midY))
        p.close()
        paintPath(p, fill, stroke, w)
      case .line(let a, let b, let c, let w):
        c.setStroke()
        let p = NSBezierPath()
        p.move(to: a)
        p.line(to: b)
        p.lineWidth = w
        p.lineCapStyle = .round
        p.stroke()
      case .text(let origin, let size, let c, let s):
        let attrs: [NSAttributedString.Key: Any] = [
          .font: NSFont.systemFont(ofSize: size, weight: .medium),
          .foregroundColor: c,
        ]
        s.draw(at: origin, withAttributes: attrs)
      case .oval(let r, let fill, let stroke, let w):
        paintPath(NSBezierPath(ovalIn: r), fill, stroke, w)
      case .triangle(let a, let b, let c, let fill, let stroke, let w):
        let p = NSBezierPath()
        p.move(to: a)
        p.line(to: b)
        p.line(to: c)
        p.close()
        paintPath(p, fill, stroke, w)
      case .poly(let pts, let fill, let stroke, let w):
        guard pts.count >= 2 else { break }
        let p = NSBezierPath()
        p.move(to: pts[0])
        for i in 1..<pts.count { p.line(to: pts[i]) }
        p.close()
        paintPath(p, fill, stroke, w)
      case .arc(let c, let r, let a0, let a1, let col, let w):
        let p = NSBezierPath()
        p.appendArc(withCenter: c, radius: r, startAngle: a0, endAngle: a1, clockwise: true)
        col.setStroke()
        p.lineWidth = w
        p.lineCapStyle = .round
        p.stroke()
      }
    }
  }

  override func mouseDown(with event: NSEvent) {
    window?.makeFirstResponder(self)
    let p = convert(event.locationInWindow, from: nil)
    lastDrag = p
    didPan = false
  }

  override func mouseDragged(with event: NSEvent) {
    let p = convert(event.locationInWindow, from: nil)
    guard let prev = lastDrag else { return }
    let dx = p.x - prev.x
    let dy = p.y - prev.y
    lastDrag = p
    if abs(dx) + abs(dy) >= 0.5 {
      didPan = true
      panBy(dx, dy)
      onDrag?(Int(dx.rounded()), Int(dy.rounded()))
    }
  }

  override func mouseUp(with event: NSEvent) {
    let p = convert(event.locationInWindow, from: nil)
    lastDrag = nil
    if !didPan {
      onClick?(Int(p.x.rounded()), Int(p.y.rounded()))
    }
    didPan = false
  }

  override func scrollWheel(with event: NSEvent) {
    var dx = event.scrollingDeltaX
    var dy = event.scrollingDeltaY
    if !event.hasPreciseScrollingDeltas {
      dx *= 8
      dy *= 8
    }
    panBy(dx, dy)
    let ix = Int(dx.rounded())
    let iy = Int(dy.rounded())
    if ix != 0 || iy != 0 {
      onScroll?(ix, iy)
    }
  }
}

private func paintPath(_ p: NSBezierPath, _ fill: NSColor?, _ stroke: NSColor?, _ w: CGFloat) {
  if let fill {
    fill.setFill()
    p.fill()
  }
  if let stroke {
    stroke.setStroke()
    p.lineWidth = w
    p.stroke()
  }
}

final class XuDrawPlugin: NSObject, XuContentPlugin {
  weak var shell: AppDelegate!
  var canvas: DrawCanvasView!
  var wantsDevToolsMenu: Bool { false }
  var penFill: NSColor = .white
  var penStroke: NSColor = .white
  var penWidth: CGFloat = 1

  init(shell: AppDelegate) {
    self.shell = shell
    super.init()
  }

  func resetPen() {
    penFill = .white
    penStroke = .white
    penWidth = 1
  }

  func install(into root: NSView, host: AppDelegate) {
    self.shell = host
    let canvas = DrawCanvasView(frame: root.bounds)
    canvas.autoresizingMask = [.width, .height]
    canvas.onClick = { [weak self] x, y in
      self?.reportClick(x: x, y: y)
    }
    canvas.onScroll = { [weak self] dx, dy in
      self?.reportScroll(dx: dx, dy: dy)
    }
    canvas.onDrag = { [weak self] dx, dy in
      self?.reportDrag(dx: dx, dy: dy)
    }
    root.addSubview(canvas)
    self.canvas = canvas
  }

  func pickFill(_ s: String) -> NSColor? {
    if s == "." { return penFill }
    return colorHex(s)
  }

  func pickStroke(_ s: String) -> NSColor? {
    if s == "." { return penStroke }
    return colorHex(s)
  }

  func pickWidth(_ s: String) -> CGFloat {
    if s == "." { return penWidth }
    return cgf(s, penWidth)
  }

  func handleCmd(_ s: String) -> Bool {
    if s == "begin" {
      canvas.ops.removeAll()
      resetPen()
      return true
    }
    if s == "present" {
      canvas.needsDisplay = true
      return true
    }
    if s == "draw_clear" {
      canvas.fillColor = NSColor(calibratedWhite: 0.10, alpha: 1)
      canvas.labelText = ""
      canvas.ops.removeAll()
      resetPen()
      canvas.needsDisplay = true
      return true
    }
    if s == "push" {
      canvas.ops.append(.push)
      return true
    }
    if s == "pop" {
      canvas.ops.append(.pop)
      return true
    }
    if s == "origin" {
      canvas.ops.append(.origin)
      return true
    }
    if s.hasPrefix("bgcolor\t") {
      let parts = splitTabs(s, max: 1)
      if parts.count >= 2, let c = colorHex(parts[1]) {
        canvas.fillColor = c
      }
      return true
    }
    if s.hasPrefix("label\t") {
      let parts = splitTabs(s, max: 1)
      if parts.count >= 2 {
        canvas.labelText = parts[1]
        if canvas.ops.isEmpty { canvas.needsDisplay = true }
      }
      return true
    }
    if s.hasPrefix("color\t") {
      let parts = splitTabs(s, max: 1)
      if parts.count >= 2, let c = colorHex(parts[1]) {
        penFill = c
        penStroke = c
      }
      return true
    }
    if s.hasPrefix("fill\t") && !s.hasPrefix("fill_rect") {
      let parts = splitTabs(s, max: 1)
      if parts.count >= 2, let c = colorHex(parts[1]) { penFill = c }
      return true
    }
    if s.hasPrefix("stroke\t") && !s.hasPrefix("stroke_rect") && !s.hasPrefix("stroke_circle") {
      let parts = splitTabs(s, max: 1)
      if parts.count >= 2, let c = colorHex(parts[1]) { penStroke = c }
      return true
    }
    if s.hasPrefix("width\t") {
      let parts = splitTabs(s, max: 1)
      if parts.count >= 2 { penWidth = cgf(parts[1], 1) }
      return true
    }
    if s.hasPrefix("translate\t") {
      let p = splitTabs(s, max: 2)
      if p.count >= 3 {
        canvas.ops.append(.translate(cgf(p[1], 0), cgf(p[2], 0)))
      }
      return true
    }
    if s.hasPrefix("rotate\t") {
      let p = splitTabs(s, max: 1)
      if p.count >= 2 { canvas.ops.append(.rotate(cgf(p[1], 0))) }
      return true
    }
    if s.hasPrefix("scale\t") {
      let p = splitTabs(s, max: 2)
      if p.count >= 3 {
        canvas.ops.append(.scale(cgf(p[1], 100) / 100, cgf(p[2], 100) / 100))
      }
      return true
    }
    if s.hasPrefix("fill_rect\t") {
      let p = splitTabs(s, max: 5)
      if p.count >= 6, let c = colorHex(p[5]) {
        canvas.ops.append(.fillRect(rect5(p), c))
      }
      return true
    }
    if s.hasPrefix("stroke_rect\t") {
      let p = splitTabs(s, max: 6)
      if p.count >= 6, let c = colorHex(p[5]) {
        let w = p.count >= 7 ? cgf(p[6], 1) : 1
        canvas.ops.append(.strokeRect(rect5(p), c, w))
      }
      return true
    }
    if s == "rect" || s.hasPrefix("rect\t") {
      let p = splitTabs(s, max: 4)
      if p.count >= 5 {
        canvas.ops.append(.fillRect(rect5(p), penFill))
      }
      return true
    }
    if s.hasPrefix("rect_line\t") {
      let p = splitTabs(s, max: 4)
      if p.count >= 5 {
        canvas.ops.append(.strokeRect(rect5(p), penStroke, penWidth))
      }
      return true
    }
    if s.hasPrefix("round_rect\t") {
      let p = splitTabs(s, max: 8)
      if p.count >= 9 {
        canvas.ops.append(
          .roundRect(rect5(p), cgf(p[5], 8), colorHex(p[6]), colorHex(p[7]), cgf(p[8], 1)))
      }
      return true
    }
    if s.hasPrefix("diamond\t") {
      let p = splitTabs(s, max: 7)
      if p.count >= 8 {
        canvas.ops.append(
          .diamond(rect5(p), colorHex(p[5]), colorHex(p[6]), cgf(p[7], 1)))
      }
      return true
    }
    if s.hasPrefix("line\t") {
      let p = splitTabs(s, max: 6)
      if p.count >= 6, let c = colorHex(p[5]) {
        let w = p.count >= 7 ? cgf(p[6], 1) : 1
        canvas.ops.append(
          .line(CGPoint(x: cgf(p[1], 0), y: cgf(p[2], 0)),
                CGPoint(x: cgf(p[3], 0), y: cgf(p[4], 0)), c, w))
      }
      return true
    }
    if s.hasPrefix("text\t") {
      let p = splitTabs(s, max: 5)
      if p.count >= 6, let c = colorHex(p[4]) {
        canvas.ops.append(
          .text(CGPoint(x: cgf(p[1], 0), y: cgf(p[2], 0)), cgf(p[3], 13), c, p[5]))
      }
      return true
    }
    if s.hasPrefix("circle_line\t") {
      let p = splitTabs(s, max: 3)
      if p.count >= 4 {
        let r = cgf(p[3], 0)
        let box = CGRect(x: cgf(p[1], 0) - r, y: cgf(p[2], 0) - r, width: r * 2, height: r * 2)
        canvas.ops.append(.oval(box, nil, penStroke, penWidth))
      }
      return true
    }
    if s.hasPrefix("circle\t") {
      let p = splitTabs(s, max: 6)
      if p.count >= 4 {
        let r = cgf(p[3], 0)
        let box = CGRect(x: cgf(p[1], 0) - r, y: cgf(p[2], 0) - r, width: r * 2, height: r * 2)
        if p.count >= 7 {
          canvas.ops.append(.oval(box, pickFill(p[4]), pickStroke(p[5]), pickWidth(p[6])))
        } else {
          canvas.ops.append(.oval(box, penFill, nil, 1))
        }
      }
      return true
    }
    if s.hasPrefix("ellipse_line\t") {
      let p = splitTabs(s, max: 4)
      if p.count >= 5 {
        canvas.ops.append(.oval(rect5(p), nil, penStroke, penWidth))
      }
      return true
    }
    if s.hasPrefix("ellipse\t") {
      let p = splitTabs(s, max: 7)
      if p.count >= 5 {
        if p.count >= 8 {
          canvas.ops.append(.oval(rect5(p), pickFill(p[5]), pickStroke(p[6]), pickWidth(p[7])))
        } else {
          canvas.ops.append(.oval(rect5(p), penFill, nil, 1))
        }
      }
      return true
    }
    if s.hasPrefix("triangle_line\t") {
      let p = splitTabs(s, max: 6)
      if p.count >= 7 {
        canvas.ops.append(
          .triangle(CGPoint(x: cgf(p[1], 0), y: cgf(p[2], 0)),
                    CGPoint(x: cgf(p[3], 0), y: cgf(p[4], 0)),
                    CGPoint(x: cgf(p[5], 0), y: cgf(p[6], 0)),
                    nil, penStroke, penWidth))
      }
      return true
    }
    if s.hasPrefix("triangle\t") {
      let p = splitTabs(s, max: 9)
      if p.count >= 7 {
        let a = CGPoint(x: cgf(p[1], 0), y: cgf(p[2], 0))
        let b = CGPoint(x: cgf(p[3], 0), y: cgf(p[4], 0))
        let c = CGPoint(x: cgf(p[5], 0), y: cgf(p[6], 0))
        if p.count >= 10 {
          canvas.ops.append(.triangle(a, b, c, pickFill(p[7]), pickStroke(p[8]), pickWidth(p[9])))
        } else {
          canvas.ops.append(.triangle(a, b, c, penFill, nil, 1))
        }
      }
      return true
    }
    if s.hasPrefix("poly\t") {
      let p = splitAll(s)
      if p.count >= 6 {
        var pts: [CGPoint] = []
        var i = 4
        while i + 1 < p.count {
          pts.append(CGPoint(x: cgf(p[i], 0), y: cgf(p[i + 1], 0)))
          i += 2
        }
        canvas.ops.append(.poly(pts, pickFill(p[1]), pickStroke(p[2]), pickWidth(p[3])))
      }
      return true
    }
    if s.hasPrefix("arc\t") {
      let p = splitTabs(s, max: 7)
      if p.count >= 7, let c = pickStroke(p[6]) {
        let w = p.count >= 8 ? pickWidth(p[7]) : penWidth
        canvas.ops.append(
          .arc(CGPoint(x: cgf(p[1], 0), y: cgf(p[2], 0)), cgf(p[3], 0),
               cgf(p[4], 0), cgf(p[5], 0), c, w))
      }
      return true
    }
    if s.hasPrefix("prompt\t") || s == "prompt" {
      // Don't runModal inside drainCmds: a nested runloop can redraw an
      // empty display list (begin already cleared ops) and the canvas stays blank.
      DispatchQueue.main.async { [weak self] in
        self?.runPrompt(s)
      }
      return true
    }
    return false
  }

  func onPoll() {}
  func syncFrame() {
    canvas?.needsDisplay = true
  }

  func evalJS(_ js: String) {
    _ = js
  }

  func snapshotPNG(to path: String, completion: @escaping (Bool) -> Void) {
    guard let canvas = canvas else {
      completion(false)
      return
    }
    guard let rep = canvas.bitmapImageRepForCachingDisplay(in: canvas.bounds) else {
      completion(false)
      return
    }
    canvas.cacheDisplay(in: canvas.bounds, to: rep)
    guard let png = rep.representation(using: .png, properties: [:]) else {
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

  func snapshotClipboard(completion: @escaping (Bool) -> Void) {
    guard let canvas = canvas else {
      completion(false)
      return
    }
    guard let rep = canvas.bitmapImageRepForCachingDisplay(in: canvas.bounds) else {
      completion(false)
      return
    }
    canvas.cacheDisplay(in: canvas.bounds, to: rep)
    let img = NSImage(size: canvas.bounds.size)
    img.addRepresentation(rep)
    NSPasteboard.general.clearContents()
    NSPasteboard.general.writeObjects([img])
    completion(true)
  }

  func onFilesDropped(_ paths: [String]) {
    let joined = paths.joined(separator: "\t")
    shell.appendShellFile("file_drop\t\(joined)")
  }

  func reportClick(x: Int, y: Int) {
    shell.appendShellFile("click\t\(x)\t\(y)")
  }

  func reportScroll(dx: Int, dy: Int) {
    shell.appendShellFile("scroll\t\(dx)\t\(dy)")
  }

  func reportDrag(dx: Int, dy: Int) {
    shell.appendShellFile("drag\t\(dx)\t\(dy)")
  }

  func runPrompt(_ s: String) {
    let parts = splitTabs(s, max: 2)
    var title = "Xu"
    var def = ""
    if parts.count >= 2 && !parts[1].isEmpty { title = parts[1] }
    if parts.count >= 3 { def = parts[2] }
    let alert = NSAlert()
    alert.messageText = title
    alert.informativeText = ""
    alert.addButton(withTitle: "OK")
    alert.addButton(withTitle: "Cancel")
    let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
    field.stringValue = def
    alert.accessoryView = field
    alert.window.initialFirstResponder = field
    let resp = alert.runModal()
    let out = resp == .alertFirstButtonReturn ? field.stringValue : ""
    var cleaned = out.replacingOccurrences(of: "\t", with: " ")
    cleaned = cleaned.replacingOccurrences(of: "\n", with: " ")
    cleaned = cleaned.replacingOccurrences(of: "\r", with: " ")
    shell.appendShellFile("prompt\t\(cleaned)")
  }
}

private func splitTabs(_ s: String, max: Int) -> [String] {
  s.split(separator: "\t", maxSplits: max, omittingEmptySubsequences: false).map(String.init)
}

private func splitAll(_ s: String) -> [String] {
  s.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
}

private func cgf(_ s: String, _ d: CGFloat) -> CGFloat {
  if let v = Double(s) { return CGFloat(v) }
  return d
}

private func rect5(_ p: [String]) -> CGRect {
  CGRect(x: cgf(p[1], 0), y: cgf(p[2], 0), width: cgf(p[3], 0), height: cgf(p[4], 0))
}

private func colorHex(_ hex: String) -> NSColor? {
  var h = hex.trimmingCharacters(in: .whitespacesAndNewlines)
  if h.isEmpty || h == "-" { return nil }
  if h.hasPrefix("#") { h = String(h.dropFirst()) }
  if h.count == 6, let n = UInt32(h, radix: 16) {
    let r = CGFloat((n >> 16) & 0xff) / 255
    let g = CGFloat((n >> 8) & 0xff) / 255
    let b = CGFloat(n & 0xff) / 255
    return NSColor(calibratedRed: r, green: g, blue: b, alpha: 1)
  }
  if h.count == 8, let n = UInt32(h, radix: 16) {
    let r = CGFloat((n >> 24) & 0xff) / 255
    let g = CGFloat((n >> 16) & 0xff) / 255
    let b = CGFloat((n >> 8) & 0xff) / 255
    let a = CGFloat(n & 0xff) / 255
    return NSColor(calibratedRed: r, green: g, blue: b, alpha: a)
  }
  return nil
}

@objc(XuDrawPluginBootstrap)
public class XuDrawPluginBootstrap: NSObject {
  @objc public static func registerPlugin() {
    XuContentRegistry.make = { host in XuDrawPlugin(shell: host) }
  }
}
