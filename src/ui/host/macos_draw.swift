import AppKit
import CoreText

private typealias ListCompile = @convention(c) (UnsafeRawPointer?) -> UnsafeMutableRawPointer?
private typealias ListDestroy = @convention(c) (UnsafeMutableRawPointer?) -> Void
@_silgen_name("xu_ui_display_list_set_backend")
private func xuListSetBackend(_ compile: ListCompile,_ destroy: ListDestroy) -> Int32
@_silgen_name("xu_ui_display_list_native")
private func xuListNative(_ list: UnsafeRawPointer?) -> UnsafeMutableRawPointer?
@_silgen_name("xu_ui_display_list_retain")
private func xuListRetain(_ list: UnsafeMutableRawPointer?)
@_silgen_name("xu_ui_display_list_release")
private func xuListRelease(_ list: UnsafeMutableRawPointer?)
@_silgen_name("xu_ui_frame_list")
private func xuFrameList(_ lease: UnsafeRawPointer?,_ id: UInt64) -> UnsafeMutableRawPointer?
private final class NativeDrawScene {
  let ops: [DrawOp]
  init(_ ops:[DrawOp]) {self.ops=ops}
}
private func compileListNative(_ lease: UnsafeRawPointer?) -> UnsafeMutableRawPointer? {
  guard let lease else {return nil}
  return autoreleasepool {
    var len:UInt32=0, images:[UInt:WeakDrawImage]=[:]
    guard let data=xuFrameData(lease,&len),let (ops,_)=decodeFrame(lease,data,len,.clear,&images) else {return nil}
    return Unmanaged.passRetained(NativeDrawScene(ops)).toOpaque()
  }
}
private func destroyListNative(_ pointer: UnsafeMutableRawPointer?) {
  if let pointer {autoreleasepool {Unmanaged<NativeDrawScene>.fromOpaque(pointer).release()}}
}
final class DrawDisplayList {
  private let resource: UnsafeMutableRawPointer
  fileprivate let native: NativeDrawScene
  init?(_ resource:UnsafeMutableRawPointer) {
    guard let pointer=xuListNative(resource) else {return nil}
    self.resource=resource;xuListRetain(resource)
    native=Unmanaged<NativeDrawScene>.fromOpaque(pointer).takeUnretainedValue()
  }
  deinit {xuListRelease(resource)}
  func draw(_ context:CGContext) {paintDrawOps(native.ops,context)}
}

private typealias SurfaceRender = @convention(c) (UnsafeRawPointer?, UInt32, UInt32, Double, Double, UnsafeMutablePointer<UInt8>?) -> Int32
@_silgen_name("xu_ui_surface_set_backend_v2")
private func xuSurfaceSetBackend(_ render: SurfaceRender,_ flags:UInt32) -> Int32
private func renderSurfaceNative(_ lease: UnsafeRawPointer?,_ width: UInt32,_ height: UInt32,
                                 _ logicalWidth: Double,_ logicalHeight: Double,_ pixels: UnsafeMutablePointer<UInt8>?) -> Int32 {
  guard let lease, let pixels else { return 0 }
  return autoreleasepool {
    var len: UInt32 = 0
    guard let data=xuFrameData(lease,&len), let space=CGColorSpace(name:CGColorSpace.sRGB),
          let context=CGContext(data:pixels,width:Int(width),height:Int(height),bitsPerComponent:8,bytesPerRow:Int(width)*4,
            space:space,bitmapInfo:CGImageAlphaInfo.premultipliedFirst.rawValue|CGBitmapInfo.byteOrder32Little.rawValue) else { return 0 }
    var images: [UInt:WeakDrawImage] = [:]
    guard let (ops,bg)=decodeFrame(lease,data,len,.clear,&images) else { return 0 }
    // CGContext memory rows begin at the top. AppKit/our frame coordinates use
    // a flipped view; reproduce it explicitly without an NSView or screen.
    context.translateBy(x:0,y:CGFloat(height)); context.scaleBy(x:CGFloat(width)/logicalWidth,y:-CGFloat(height)/logicalHeight)
    let previous=NSGraphicsContext.current
    NSGraphicsContext.current=NSGraphicsContext(cgContext:context,flipped:true)
    defer { NSGraphicsContext.current=previous }
    bg.setFill(); context.fill(CGRect(x:0,y:0,width:logicalWidth,height:logicalHeight))
    paintDrawOps(ops,context); context.flush()
    return 1
  }
}

private typealias TextCreate = @convention(c) (UnsafePointer<CChar>?, UInt32, UnsafePointer<CChar>?, UInt32,
  UnsafePointer<Double>?, UnsafeMutablePointer<Double>?, UnsafeMutablePointer<UInt32>?) -> UnsafeMutableRawPointer?
private typealias TextDestroy = @convention(c) (UnsafeMutableRawPointer?) -> Void
private typealias TextQuery = @convention(c) (UnsafeMutableRawPointer?, UInt32, UInt32, UInt32,
  Double, Double, UnsafeMutablePointer<Double>?) -> Int32
@_silgen_name("xu_ui_text_set_backend")
private func xuTextSetBackend(_ create: TextCreate, _ destroy: TextDestroy) -> Int32
@_silgen_name("xu_ui_text_set_query_backend")
private func xuTextSetQueryBackend(_ query: TextQuery) -> Int32
@_silgen_name("xu_ui_frame_text")
private func xuFrameText(_ frame: UnsafeRawPointer?, _ id: UInt64) -> UnsafeMutableRawPointer?
@_silgen_name("xu_ui_frame_path")
private func xuFramePath(_ frame: UnsafeRawPointer?, _ offset: UInt32, _ length: UnsafeMutablePointer<UInt32>?) -> UnsafeRawPointer?
@_silgen_name("xu_ui_text_native")
private func xuTextNative(_ text: UnsafeRawPointer?) -> UnsafeMutableRawPointer?
@_silgen_name("xu_ui_text_retain")
private func xuTextRetain(_ text: UnsafeMutableRawPointer?)
@_silgen_name("xu_ui_text_release")
private func xuTextRelease(_ text: UnsafeMutableRawPointer?)

// CoreText objects retain the shaped lines used for both metrics and drawing.
// No NSView, NSFontManager, or UI-thread text container is accessed by workers.
private final class NativeTextLayout {
  let frame: CTFrame
  let height: CGFloat
  let source: NSString
  let byteOffsets: [UInt32]
  let lines: [CTLine]
  let origins: [CGPoint]
  let lock = NSLock()
  init(_ frame: CTFrame, _ height: CGFloat, _ source: String, _ lines: [CTLine], _ origins: [CGPoint]) {
    self.frame = frame; self.height = height; self.source = source as NSString; self.lines = lines; self.origins = origins
    var offsets = [UInt32](), bytes: UInt32 = 0
    for scalar in source.unicodeScalars {
      offsets.append(bytes); if scalar.value > 65535 { offsets.append(bytes) }
      bytes += UInt32(scalar.utf8.count)
    }
    offsets.append(bytes); byteOffsets = offsets
  }
}
private func createTextNative(_ family: UnsafePointer<CChar>?, _ familyLength: UInt32,
  _ text: UnsafePointer<CChar>?, _ length: UInt32, _ options: UnsafePointer<Double>?,
  _ metrics: UnsafeMutablePointer<Double>?, _ cost: UnsafeMutablePointer<UInt32>?) -> UnsafeMutableRawPointer? {
  guard let v = options, let metrics, let cost else { return nil }
  func string(_ pointer: UnsafePointer<CChar>?, _ count: UInt32) -> String {
    guard count > 0, let pointer else { return "" }
    return String(decoding: UnsafeBufferPointer(start: UnsafeRawPointer(pointer).assumingMemoryBound(to: UInt8.self), count: Int(count)), as: UTF8.self)
  }
  let familyName = string(family, familyLength)
  var value = string(text, length)
  let original = value
  // CTFramesetter omits an empty final paragraph. The zero-width glyph keeps
  // its line box without changing advances, including a completely empty text.
  let last = value.unicodeScalars.last?.value
  if value.isEmpty || last == 10 || last == 13 || last == 0x2028 || last == 0x2029 { value += "\u{200B}" }
  let base: CTFont
  if familyName.isEmpty {
    guard let system = CTFontCreateUIFontForLanguage(.system, CGFloat(v[0]), nil) else { return nil }
    base = system
  } else { base = CTFontCreateWithName(familyName as CFString, CGFloat(v[0]), nil) }
  let weight = CGFloat((v[2] - 400) / (v[2] < 400 ? 300 : 500))
  let descriptor = CTFontDescriptorCreateCopyWithAttributes(CTFontCopyFontDescriptor(base),
    [kCTFontTraitsAttribute: [kCTFontWeightTrait: weight]] as CFDictionary)
  var font = CTFontCreateWithFontDescriptor(descriptor, CGFloat(v[0]), nil)
  if v[3] != 0, let italic = CTFontCreateCopyWithSymbolicTraits(font, 0, nil, .italicTrait, .italicTrait) { font = italic }
  var alignment: CTTextAlignment = v[4] == 1 ? .center : v[4] == 2 ? .right : .left
  var breakMode: CTLineBreakMode = v[1] == 0 ? .byClipping : .byWordWrapping
  var lineHeight = CGFloat(v[5])
  let paragraph: CTParagraphStyle = withUnsafePointer(to: &alignment) { a in
    withUnsafePointer(to: &breakMode) { b in
      withUnsafePointer(to: &lineHeight) { h in
        var settings = [CTParagraphStyleSetting(spec: .alignment, valueSize: MemoryLayout<CTTextAlignment>.size, value: a),
                        CTParagraphStyleSetting(spec: .lineBreakMode, valueSize: MemoryLayout<CTLineBreakMode>.size, value: b)]
        if v[5] > 0 {
          settings.append(CTParagraphStyleSetting(spec: .minimumLineHeight, valueSize: MemoryLayout<CGFloat>.size, value: h))
          settings.append(CTParagraphStyleSetting(spec: .maximumLineHeight, valueSize: MemoryLayout<CGFloat>.size, value: h))
        }
        return CTParagraphStyleCreate(settings, settings.count)
      }
    }
  }
  let attributed = NSAttributedString(string: value, attributes: [
    NSAttributedString.Key(kCTFontAttributeName as String): font,
    NSAttributedString.Key(kCTParagraphStyleAttributeName as String): paragraph,
    NSAttributedString.Key(kCTForegroundColorFromContextAttributeName as String): true])
  let setter = CTFramesetterCreateWithAttributedString(attributed)
  let width = v[1] > 0 ? CGFloat(v[1]) : 1048576
  let suggested = CTFramesetterSuggestFrameSizeWithConstraints(setter, CFRange(location: 0, length: 0), nil,
    CGSize(width: width, height: 1048576), nil)
  guard suggested.height.isFinite, suggested.height < 1048575 else { return nil }
  let height = max(1, ceil(suggested.height) + 1)
  let frame = CTFramesetterCreateFrame(setter, CFRange(location: 0, length: 0),
    CGPath(rect: CGRect(x: 0, y: 0, width: width, height: height), transform: nil), nil)
  let lines = CTFrameGetLines(frame) as! [CTLine]
  guard !lines.isEmpty else { return nil }
  // A full layout must contain all of the input; never silently drop overflow.
  let range = CTFrameGetVisibleStringRange(frame)
  guard range.location == 0, range.length == attributed.length else { return nil }
  var origins = [CGPoint](repeating: .zero, count: lines.count)
  CTFrameGetLineOrigins(frame, CFRange(location: 0, length: 0), &origins)
  var advance: Double = 0, baseline: Double = 0, bottom: Double = 0
  var ink = CGRect.null
  for (i, line) in lines.enumerated() {
    var ascent: CGFloat = 0, descent: CGFloat = 0, leading: CGFloat = 0
    advance = max(advance, CTLineGetTypographicBounds(line, &ascent, &descent, &leading))
    let lineBaseline = height - origins[i].y
    if i == 0 { baseline = Double(lineBaseline) }
    bottom = max(bottom, Double(lineBaseline + descent))
    let bounds = CTLineGetBoundsWithOptions(line, .useGlyphPathBounds)
    if !bounds.isEmpty { ink = ink.union(CGRect(x: origins[i].x + bounds.minX, y: lineBaseline - bounds.maxY, width: bounds.width, height: bounds.height)) }
  }
  metrics[0] = advance; metrics[1] = max(bottom, v[5] > 0 ? v[5] * Double(lines.count) : bottom)
  metrics[2] = baseline; metrics[3] = Double(lines.count)
  metrics[4] = ink.isNull ? 0 : Double(ink.minX); metrics[5] = ink.isNull ? 0 : Double(ink.minY)
  metrics[6] = ink.isNull ? 0 : Double(ink.width); metrics[7] = ink.isNull ? 0 : Double(ink.height)
  cost.pointee = 8192 + length * 128
  return Unmanaged.passRetained(NativeTextLayout(frame, height, original, lines, origins)).toOpaque()
}
private func queryTextNative(_ pointer: UnsafeMutableRawPointer?, _ mode: UInt32, _ index: UInt32, _ trailing: UInt32,
  _ x: Double, _ y: Double, _ out: UnsafeMutablePointer<Double>?) -> Int32 {
  guard let pointer, let out else { return 0 }
  let text = Unmanaged<NativeTextLayout>.fromOpaque(pointer).takeUnretainedValue()
  text.lock.lock(); defer { text.lock.unlock() }
  var lineIndex = text.lines.count - 1, at = text.source.length, edge = trailing != 0, inside = true
  if mode == 0 {
    var closest = Double.infinity
    for i in text.lines.indices {
      var ascent: CGFloat = 0, descent: CGFloat = 0
      _ = CTLineGetTypographicBounds(text.lines[i], &ascent, &descent, nil)
      let top = Double(text.height - text.origins[i].y - ascent), bottom = top + Double(ascent + descent)
      let distance = max(top - y, y - bottom, 0)
      if distance < closest { closest = distance; lineIndex = i }
    }
    let line = text.lines[lineIndex], origin = text.origins[lineIndex]
    let range = CTLineGetStringRange(line)
    let position = CTLineGetStringIndexForPosition(line, CGPoint(x: x - Double(origin.x), y: 0))
    at = position == kCFNotFound ? (x < Double(origin.x) ? range.location : range.location + range.length) : position
    at = max(0, min(at, text.source.length))
    if at > range.location && at >= range.location + range.length { at -= 1 }
    var ascent: CGFloat = 0, descent: CGFloat = 0
    let width = CTLineGetTypographicBounds(line, &ascent, &descent, nil)
    let top = Double(text.height - origin.y - ascent)
    inside = x >= Double(origin.x) && x <= Double(origin.x) + width && y >= top && y <= top + Double(ascent + descent)
  } else {
    guard let position = text.byteOffsets.firstIndex(of: index) else { return 0 }
    at = position
    for i in text.lines.indices {
      let range = CTLineGetStringRange(text.lines[i])
      if at >= range.location && at < range.location + range.length { lineIndex = i; break }
    }
  }
  var range = at < text.source.length ? text.source.rangeOfComposedCharacterSequence(at: at) : NSRange(location: at, length: 0)
  let line = text.lines[lineIndex], origin = text.origins[lineIndex]
  if mode == 0 {
    // CoreText returns an insertion index. A trailing-half hit can therefore
    // name the next grapheme: compare its two neighboring advance intervals.
    var candidates = [range]
    if at > 0 { candidates.append(text.source.rangeOfComposedCharacterSequence(at: at - 1)) }
    var nearest = Double.infinity
    let lineRange = CTLineGetStringRange(line)
    for candidate in candidates where candidate.location >= lineRange.location && candidate.location <= lineRange.location + lineRange.length {
      let a = Double(CTLineGetOffsetForStringIndex(line, candidate.location, nil)) + Double(origin.x)
      let b = Double(CTLineGetOffsetForStringIndex(line, candidate.location + candidate.length, nil)) + Double(origin.x)
      let distance = max(min(a,b) - x, x - max(a,b), 0)
      if distance < nearest { nearest = distance; range = candidate }
    }
  }
  let leading = Double(CTLineGetOffsetForStringIndex(line, range.location, nil)) + Double(origin.x)
  let ending = Double(CTLineGetOffsetForStringIndex(line, range.location + range.length, nil)) + Double(origin.x)
  if mode == 0 { edge = abs(x - ending) < abs(x - leading) }
  var ascent: CGFloat = 0, descent: CGFloat = 0
  _ = CTLineGetTypographicBounds(line, &ascent, &descent, nil)
  guard range.location + range.length < text.byteOffsets.count else { return 0 }
  out[0] = Double(text.byteOffsets[range.location])
  out[1] = Double(text.byteOffsets[range.location + range.length]) - out[0]
  out[2] = edge ? 1 : 0; out[3] = inside ? 1 : 0
  out[4] = edge ? ending : leading; out[5] = Double(text.height - origin.y - ascent); out[6] = Double(ascent + descent)
  return 1
}
@_cdecl("xu_draw_text_init")
func xuDrawTextInit() {
  _ = xuSurfaceSetBackend(renderSurfaceNative,1)
  _ = xuListSetBackend(compileListNative,destroyListNative)
  _ = xuTextSetQueryBackend(queryTextNative)
  _ = xuTextSetBackend(createTextNative, { pointer in
    if let pointer { Unmanaged<NativeTextLayout>.fromOpaque(pointer).release() }
  })
}
final class DrawText {
  private let resource: UnsafeMutableRawPointer
  private let native: NativeTextLayout
  init?(_ resource: UnsafeMutableRawPointer) {
    guard let pointer = xuTextNative(resource) else { return nil }
    self.resource = resource; xuTextRetain(resource)
    native = Unmanaged<NativeTextLayout>.fromOpaque(pointer).takeUnretainedValue()
  }
  deinit { xuTextRelease(resource) }
  func draw(_ context: CGContext, _ origin: CGPoint, _ color: NSColor) {
    native.lock.lock(); defer { native.lock.unlock() }
    context.saveGState(); context.setFillColor(color.cgColor)
    context.translateBy(x: origin.x, y: origin.y + native.height); context.scaleBy(x: 1, y: -1)
    context.textMatrix = .identity
    CTFrameDraw(native.frame, context); context.restoreGState()
  }
}
@_silgen_name("xu_ui_request_take")
private func xuRequestTake(_ id: UInt64, _ canvas: UInt32, _ generation: UInt32) -> UnsafeMutablePointer<CChar>?
@_silgen_name("xu_ui_request_alive")
private func xuRequestAlive(_ id: UInt64) -> Int32
@_silgen_name("xu_ui_request_complete")
private func xuRequestComplete(_ id: UInt64, _ status: UInt32, _ text: UnsafePointer<CChar>?, _ length: UInt32) -> Int32
@_silgen_name("xu_ui_request_poll")
private func xuRequestPoll()
@_silgen_name("xu_ui_text_input_poll")
private func xuTextInputPoll()

private func requestText(_ value: Substring) -> String? {
  let digits = Array(value.utf8)
  guard digits.count % 2 == 0, digits.count <= 131072 else { return nil }
  func nibble(_ c: UInt8) -> UInt8? {
    if c >= 48 && c <= 57 { return c - 48 }
    if c >= 97 && c <= 102 { return c - 87 }
    return nil
  }
  var bytes = [UInt8](); bytes.reserveCapacity(digits.count / 2)
  for i in stride(from: 0, to: digits.count, by: 2) {
    guard let a = nibble(digits[i]), let b = nibble(digits[i + 1]), a != 0 || b != 0 else { return nil }
    bytes.append(a * 16 + b)
  }
  return String(bytes: bytes, encoding: .utf8)
}

private func completeRequest(_ id: UInt64, _ status: UInt32, _ value: String = "") {
  value.withCString { _ = xuRequestComplete(id, status, $0, UInt32(value.utf8.count)) }
}

@_silgen_name("xu_ui_draw_acquire_for")
private func xuDrawAcquire(_ ticket: UInt64, _ canvas: UInt32, _ generation: UInt32) -> UnsafeMutableRawPointer?
@_silgen_name("xu_ui_frame_data")
private func xuFrameData(_ frame: UnsafeRawPointer?, _ len: UnsafeMutablePointer<UInt32>?) -> UnsafeRawPointer?
@_silgen_name("xu_ui_frame_bitmap")
private func xuFrameBitmap(_ frame: UnsafeRawPointer?, _ image: UInt64) -> UnsafeMutableRawPointer?
@_silgen_name("xu_ui_frame_release")
private func xuFrameRelease(_ frame: UnsafeMutableRawPointer?)
@_silgen_name("xu_ui_bitmap_pixels")
private func xuBitmapPixels(_ bitmap: UnsafeRawPointer?, _ width: UnsafeMutablePointer<UInt32>?, _ height: UnsafeMutablePointer<UInt32>?) -> UnsafePointer<UInt8>?
@_silgen_name("xu_ui_bitmap_retain")
private func xuBitmapRetain(_ bitmap: UnsafeMutableRawPointer?)
@_silgen_name("xu_ui_bitmap_release")
private func xuBitmapRelease(_ bitmap: UnsafeMutableRawPointer?)
@_silgen_name("xu_ui_canvas_open")
private func xuCanvasOpen(_ window: UInt32, _ canvas: UInt32) -> UInt32
@_silgen_name("xu_ui_canvas_close")
private func xuCanvasClose(_ canvas: UInt32, _ generation: UInt32)
@_silgen_name("xu_ui_draw_next_v2")
private func xuDrawNext(_ data: UnsafeRawPointer?, _ len: UInt32, _ cursor: UnsafeMutablePointer<UInt32>?,
                        _ values: UnsafeMutablePointer<Double>?, _ meta: UnsafeMutablePointer<UInt32>?,
                        _ text: UnsafeMutablePointer<UnsafePointer<CChar>?>?, _ textLen: UnsafeMutablePointer<UInt32>?,
                        _ imageID: UnsafeMutablePointer<UInt64>?) -> Int32

// A distinct NSTextInputClient for each focus lifetime keeps delayed callbacks
// bound to their original session. NSTextInputContext does not retain its client.
@_silgen_name("xu_ui_text_input_snapshot")
private func xuInputSnapshot(_ id: UInt64, _ canvas: UInt32, _ generation: UInt32, _ take: Int32, _ length: UnsafeMutablePointer<UInt32>?) -> UnsafeMutableRawPointer?
@_silgen_name("xu_ui_text_input_active")
private func xuInputActive(_ id: UInt64) -> Int32
@_silgen_name("xu_ui_text_input_activate")
private func xuInputActivate(_ id: UInt64, _ canvas: UInt32, _ generation: UInt32) -> Int32
@_silgen_name("xu_ui_text_input_stop")
private func xuInputStop(_ id: UInt64, _ canvas: UInt32, _ generation: UInt32, _ reason: UInt32) -> Int32
@_silgen_name("xu_ui_text_input_commit")
private func xuInputCommit(_ id: UInt64, _ value: UnsafePointer<CChar>?, _ length: UInt32, _ start: UInt32, _ end: UInt32) -> Int32
@_silgen_name("xu_ui_text_input_commit_at")
private func xuInputCommitAt(_ id: UInt64, _ revision: UInt64, _ value: UnsafePointer<CChar>?, _ length: UInt32, _ start: UInt32, _ end: UInt32) -> Int32
@_silgen_name("xu_ui_text_input_compose_at")
private func xuInputComposeAt(_ id: UInt64, _ revision: UInt64, _ value: UnsafePointer<CChar>?, _ length: UInt32, _ anchor: UInt32, _ focus: UInt32, _ start: UInt32, _ end: UInt32) -> Int32
@_silgen_name("xu_ui_text_input_query")
private func xuInputQuery(_ id: UInt64, _ canvas: UInt32, _ generation: UInt32, _ revision: UInt64, _ mode: UInt32,
  _ index: UInt32, _ trailing: UInt32, _ x: Double, _ y: Double, _ result: UnsafeMutablePointer<Double>?) -> Int32
@_silgen_name("xu_ui_text_input_select_all")
private func xuInputSelectAll(_ id: UInt64) -> Int32
@_silgen_name("xu_ui_text_input_compose")
private func xuInputCompose(_ id: UInt64, _ value: UnsafePointer<CChar>?, _ length: UInt32, _ anchor: UInt32, _ focus: UInt32, _ start: UInt32, _ end: UInt32) -> Int32
@_silgen_name("xu_ui_text_input_cancel")
private func xuInputCancel(_ id: UInt64) -> Int32
@_silgen_name("xu_ui_text_input_select")
private func xuInputSelect(_ id: UInt64, _ anchor: UInt32, _ focus: UInt32) -> Int32
@_silgen_name("xu_ui_text_input_erase")
private func xuInputErase(_ id: UInt64, _ backward: Int32) -> Int32
@_silgen_name("xu_ui_text_input_move")
private func xuInputMove(_ id: UInt64, _ backward: Int32, _ extend: Int32) -> Int32

struct InputUTFMap {
  let value: String
  let bytes: [UInt8]
  let utf16Bytes: [Int] // -1 denotes the interior of a surrogate pair.
  init(_ value: String) {
    self.value = value; bytes = Array(value.utf8)
    var table = [0], byte = 0
    for scalar in value.unicodeScalars {
      if scalar.value > 0xffff { table.append(-1) }
      byte += scalar.utf8.count; table.append(byte)
    }
    utf16Bytes = table
  }
  func byteRange(_ range: NSRange) -> (Int, Int)? {
    guard range.location != NSNotFound, range.location >= 0, range.location < utf16Bytes.count,
          range.length >= 0, range.length <= utf16Bytes.count - 1 - range.location else { return nil }
    let a = utf16Bytes[range.location], b = utf16Bytes[range.location + range.length]
    return a >= 0 && b >= 0 ? (a, b) : nil
  }
  func range(_ a: Int, _ b: Int) -> NSRange? {
    guard let first = utf16Bytes.firstIndex(of: a), let last = utf16Bytes.firstIndex(of: b), last >= first else { return nil }
    return NSRange(location: first, length: last - first)
  }
  func boundary(_ byte: Int) -> Bool {
    return byte >= 0 && byte <= bytes.count && (byte == bytes.count || bytes[byte] & 0xc0 != 0x80)
  }
}

struct NativeInputState {
  let id: UInt64, revision: UInt64
  let canvas: UInt32, generation: UInt32, flags: UInt32, serial: UInt32
  let source: String, preedit: String
  let anchor: Int, focus: Int, start: Int, end: Int, markedAnchor: Int, markedFocus: Int
  let caret: NSRect
  var composing: Bool { flags & 4 != 0 }
  var display: String {
    if !composing { return source }
    let bytes = Array(source.utf8)
    return String(decoding: bytes[..<start] + Array(preedit.utf8) + bytes[end...], as: UTF8.self)
  }
  var displayAnchor: Int { composing ? start + markedAnchor : anchor }
  var displayFocus: Int { composing ? start + markedFocus : focus }
  func sourceIndex(_ index: Int, after: Bool) -> Int {
    let count = preedit.utf8.count
    if !composing || index < start { return index }
    if count == 0 && index == start { return after ? end : start }
    if index == start { return start }
    if index >= start + count { return index - count + end - start }
    return after ? end : start
  }
  static func read(_ id: UInt64, _ canvas: UInt32, _ generation: UInt32, take: Bool = false) -> NativeInputState? {
    var length: UInt32 = 0
    guard let p = xuInputSnapshot(id, canvas, generation, take ? 1 : 0, &length) else { return nil }
    defer { free(p) }
    guard length >= 112, length <= 32880 else { return nil }
    func u16(_ offset: Int) -> UInt16 { p.loadUnaligned(fromByteOffset: offset, as: UInt16.self).littleEndian }
    func u32(_ offset: Int) -> UInt32 { p.loadUnaligned(fromByteOffset: offset, as: UInt32.self).littleEndian }
    func u64(_ offset: Int) -> UInt64 { p.loadUnaligned(fromByteOffset: offset, as: UInt64.self).littleEndian }
    func f64(_ offset: Int) -> Double { Double(bitPattern: u64(offset)) }
    guard u32(0) == 0x31534958, u16(4) == 1, u16(6) <= 7, u64(8) == id, id > 0, id <= Int64.max,
          u32(20) == canvas, u32(24) == generation, generation != 0, u32(28) == 2, u32(108) == 0,
          u64(32) > 0, u64(32) <= Int64.max, u32(104) != 0,
          u32(80) <= 16384, u32(84) <= 16384, length == 112 + u32(80) + u32(84) else { return nil }
    let sourceBytes = UnsafeRawBufferPointer(start: p.advanced(by: 112), count: Int(u32(80)))
    let preeditBytes = UnsafeRawBufferPointer(start: p.advanced(by: 112 + Int(u32(80))), count: Int(u32(84)))
    guard !sourceBytes.contains(0), !preeditBytes.contains(0),
          let source = String(bytes: sourceBytes, encoding: .utf8), let preedit = String(bytes: preeditBytes, encoding: .utf8) else { return nil }
    let src = InputUTFMap(source), mark = InputUTFMap(preedit)
    let a = Int(u32(72)), f = Int(u32(76)), start = Int(u32(88)), end = Int(u32(92))
    let ma = Int(u32(96)), mf = Int(u32(100)), composing = u16(6) & 4 != 0
    guard src.boundary(a), src.boundary(f), start <= end, src.boundary(start), src.boundary(end),
          mark.boundary(ma), mark.boundary(mf), src.bytes.count - (end - start) + mark.bytes.count <= 16384,
          composing || (preedit.isEmpty && start == 0 && end == 0 && ma == 0 && mf == 0) else { return nil }
    let coords = [f64(40), f64(48), f64(56), f64(64)]
    guard coords.allSatisfy({ $0.isFinite && abs($0) <= 1048576 }), coords[2] >= 0, coords[2] <= 16384,
          coords[3] > 0, coords[3] <= 16384 else { return nil }
    return NativeInputState(id: id, revision: u64(32), canvas: canvas, generation: generation, flags: UInt32(u16(6)), serial: u32(104),
      source: source, preedit: preedit, anchor: a, focus: f, start: start, end: end, markedAnchor: ma, markedFocus: mf,
      caret: NSRect(x: coords[0], y: coords[1], width: coords[2], height: coords[3]))
  }
}

final class DrawInputClient: NSResponder, NSTextInputClient {
  weak var view: DrawCanvasView?
  let id: UInt64, canvas: UInt32, generation: UInt32
  var context: NSTextInputContext!
  var retired = false
  var lastCoordinates: [Double] = []
  var lastRevision: UInt64 = 0
  var lastSerial: UInt32 = 0
  init(view: DrawCanvasView, id: UInt64) {
    self.view = view; self.id = id; canvas = view.canvasID; generation = view.generation
    super.init(); context = NSTextInputContext(client: self)
  }
  required init?(coder: NSCoder) { nil }
  func current() -> NativeInputState? {
    guard !retired, let view, view.textInputClient === self, view.window?.firstResponder === view,
          view.window?.isKeyWindow == true else { return nil }
    return NativeInputState.read(id, canvas, generation)
  }
  func failed() { _ = xuInputStop(id, canvas, generation, 3) }
  func shutdown() {
    retired = true; view = nil
    // Deactivate first so neither discard nor late IME replies can commit.
    context.deactivate(); context.discardMarkedText()
  }
  func refresh() {
    guard let state = current(), let view else { return }
    let caret = geometry(state, 3, 0, 0)?.rect ?? state.caret
    let rect = view.convert(caret.offsetBy(dx: -view.camX, dy: -view.camY), to: nil)
    let key: [Double] = [Double(rect.minX), Double(rect.minY),
                        Double(rect.width), Double(rect.height), Double(view.window?.frame.minX ?? 0), Double(view.window?.frame.minY ?? 0)]
    if key != lastCoordinates || state.revision != lastRevision || state.serial != lastSerial {
      lastCoordinates = key; lastRevision = state.revision; lastSerial = state.serial
      context.invalidateCharacterCoordinates()
    }
  }
  func replacement(_ range: NSRange, _ state: NativeInputState) -> (UInt32, UInt32)? {
    if range.location == NSNotFound { return (UInt32.max, UInt32.max) }
    guard let (a, b) = InputUTFMap(state.display).byteRange(range) else { return nil }
    return (UInt32(state.sourceIndex(a, after: false)), UInt32(state.sourceIndex(b, after: true)))
  }
  func value(_ object: Any) -> String? {
    let text: String
    if let attributed = object as? NSAttributedString { text = attributed.string }
    else if let string = object as? String { text = string }
    else { return nil }
    return text.utf8.count <= 16384 && !text.utf8.contains(0) ? text : nil
  }
  func insertText(_ object: Any, replacementRange: NSRange) {
    guard let state = current() else { return }
    guard let text = value(object), let (a, b) = replacement(replacementRange, state) else { failed(); return }
    if text.withCString({ xuInputCommitAt(id, state.revision, $0, UInt32(text.utf8.count), a, b) }) == 0 { failed() }
  }
  func setMarkedText(_ object: Any, selectedRange: NSRange, replacementRange: NSRange) {
    guard let state = current() else { return }
    guard let text = value(object), let (a, b) = replacement(replacementRange, state),
          let (anchor, focus) = InputUTFMap(text).byteRange(selectedRange) else { failed(); return }
    if text.withCString({ xuInputComposeAt(id, state.revision, $0, UInt32(text.utf8.count), UInt32(anchor), UInt32(focus), a, b) }) == 0 { failed() }
  }
  func unmarkText() {
    guard let state = current(), state.composing else { return }
    if state.preedit.withCString({ xuInputCommitAt(id, state.revision, $0, UInt32(state.preedit.utf8.count), UInt32.max, UInt32.max) }) == 0 { failed() }
  }
  func selectedRange() -> NSRange {
    guard let state = current() else { return NSRange(location: NSNotFound, length: 0) }
    return InputUTFMap(state.display).range(min(state.displayAnchor, state.displayFocus), max(state.displayAnchor, state.displayFocus)) ?? NSRange(location: NSNotFound, length: 0)
  }
  func markedRange() -> NSRange {
    guard let state = current(), state.composing else { return NSRange(location: NSNotFound, length: 0) }
    return InputUTFMap(state.display).range(state.start, state.start + state.preedit.utf8.count) ?? NSRange(location: NSNotFound, length: 0)
  }
  func hasMarkedText() -> Bool { current()?.composing == true }
  func attributedSubstring(forProposedRange range: NSRange, actualRange: NSRangePointer?) -> NSAttributedString? {
    actualRange?.pointee = NSRange(location: NSNotFound, length: 0)
    guard let state = current(), range.location != NSNotFound, range.location >= 0, range.length >= 0 else { return nil }
    let map = InputUTFMap(state.display), count = map.utf16Bytes.count - 1
    guard range.location <= count else { return nil }
    var first = range.location, last = first + min(range.length, count - first)
    if map.utf16Bytes[first] < 0 { first -= 1 }
    if map.utf16Bytes[last] < 0 { last += 1 }
    let result = NSRange(location: first, length: last - first)
    actualRange?.pointee = result
    return NSAttributedString(string: (map.value as NSString).substring(with: result))
  }
  func validAttributesForMarkedText() -> [NSAttributedString.Key] { [] }
  func geometry(_ state: NativeInputState, _ mode: UInt32, _ index: Int, _ trailing: UInt32,
                _ point: NSPoint = .zero) -> (index: Int, length: Int, trailing: Bool, rect: NSRect)? {
    guard index >= 0, index <= 16384 else { return nil }
    var result = [Double](repeating: 0, count: 8)
    guard xuInputQuery(id, canvas, generation, state.revision, mode, UInt32(index), trailing,
                       Double(point.x), Double(point.y), &result) != 0 else { return nil }
    return (Int(result[0]), Int(result[1]), result[2] != 0,
            NSRect(x: result[4], y: result[5], width: result[6], height: result[7]))
  }
  func firstRect(forCharacterRange range: NSRange, actualRange: NSRangePointer?) -> NSRect {
    actualRange?.pointee = NSRange(location: NSNotFound, length: 0)
    guard let state = current(), let view, let window = view.window else { return .zero }
    let map = InputUTFMap(state.display)
    guard let (first, _) = map.byteRange(range) else { return .zero }
    if let hit = geometry(state, range.length == 0 ? 1 : 2, first, 0) {
      let start = hit.index + (hit.trailing ? hit.length : 0)
      actualRange?.pointee = map.range(start, range.length == 0 ? start : hit.index + hit.length) ?? NSRange(location: NSNotFound, length: 0)
      return window.convertToScreen(view.convert(hit.rect.offsetBy(dx: -view.camX, dy: -view.camY), to: nil))
    }
    // An unbound/newly edited document has only the explicitly supplied caret.
    actualRange?.pointee = map.range(state.displayFocus, state.displayFocus) ?? NSRange(location: NSNotFound, length: 0)
    return window.convertToScreen(view.convert(state.caret.offsetBy(dx: -view.camX, dy: -view.camY), to: nil))
  }
  func characterIndex(for point: NSPoint) -> Int {
    guard let state = current(), let view, let window = view.window else { return NSNotFound }
    var local = view.convert(window.convertPoint(fromScreen: point), from: nil)
    local.x += view.camX; local.y += view.camY
    guard let hit = geometry(state, 0, 0, 0, local),
          let range = InputUTFMap(state.display).range(hit.index + (hit.trailing ? hit.length : 0), hit.index + (hit.trailing ? hit.length : 0)) else { return NSNotFound }
    return range.location
  }
  override func doCommand(by selector: Selector) {
    guard let state = current() else { return }
    let command = NSStringFromSelector(selector)
    if state.composing && command != "cancelOperation:" && command != "selectAll:" { return }
    var accepted: Int32
    switch command {
    case "cancelOperation:":
      accepted = xuInputCancel(id); context.discardMarkedText()
    case "selectAll:":
      accepted = xuInputCancel(id)
      if accepted != 0 { accepted = xuInputSelectAll(id) }
    case "deleteBackward:": accepted = xuInputErase(id, 1)
    case "deleteForward:": accepted = xuInputErase(id, 0)
    case "moveLeft:", "moveBackward:": accepted = xuInputMove(id, 1, 0)
    case "moveRight:", "moveForward:": accepted = xuInputMove(id, 0, 0)
    case "moveLeftAndModifySelection:", "moveBackwardAndModifySelection:": accepted = xuInputMove(id, 1, 1)
    case "moveRightAndModifySelection:", "moveForwardAndModifySelection:": accepted = xuInputMove(id, 0, 1)
    case "insertNewline:", "insertLineBreak:":
      guard state.flags & 1 != 0 else { return }
      accepted = "\n".withCString { xuInputCommit(id, $0, 1, UInt32.max, UInt32.max) }
    default: return
    }
    if accepted == 0 { failed() }
  }
}

final class DrawImage {
  let image: CGImage
  init?(_ bitmap: UnsafeMutableRawPointer) {
    var width: UInt32 = 0, height: UInt32 = 0
    guard let pixels = xuBitmapPixels(bitmap, &width, &height) else { return nil }
    xuBitmapRetain(bitmap)
    guard let provider = CGDataProvider(dataInfo: bitmap, data: pixels, size: Int(width) * Int(height) * 4,
      releaseData: { info, _, _ in xuBitmapRelease(info) }) else { xuBitmapRelease(bitmap); return nil }
    guard let space = CGColorSpace(name: CGColorSpace.sRGB),
      let image = CGImage(width: Int(width), height: Int(height), bitsPerComponent: 8, bitsPerPixel: 32,
        bytesPerRow: Int(width) * 4, space: space,
        bitmapInfo: CGBitmapInfo(rawValue: CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue),
        provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent) else { return nil }
    self.image = image
  }
}
final class WeakDrawImage {
  weak var value: DrawImage?
  init(_ value: DrawImage) { self.value = value }
}

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

final class DrawVectorPath {
  let path: CGPath
  let flags: UInt32
  let width: CGFloat, miter: CGFloat
  init?(_ data: UnsafeRawPointer, _ length: UInt32) {
    let bytes = UnsafeRawBufferPointer(start: data, count: Int(length))
    guard bytes.count >= 48 else { return nil }
    func word(_ at: Int) -> UInt32 { (0..<4).reduce(UInt32(0)) { $0 | (UInt32(bytes[at+$1]) << ($1*8)) } }
    func scalar(_ at: Int) -> CGFloat {
      let bits = (0..<8).reduce(UInt64(0)) { $0 | (UInt64(bytes[at+$1]) << ($1*8)) }
      return CGFloat(Double(bitPattern: bits))
    }
    flags = word(0); width = scalar(16); miter = scalar(24)
    guard word(12) == 0, word(8) <= 32768 else { return nil }
    let result = CGMutablePath()
    var cursor = 48, current = CGPoint.zero, drawn = false
    for _ in 0..<word(8) {
      guard cursor <= bytes.count-4 else { return nil }
      let verb = word(cursor), count = verb == 1 || verb == 2 ? 2 : verb == 3 ? 4 : verb == 4 ? 6 : 0
      cursor += 4
      guard verb >= 1, verb <= 5, count*8 <= bytes.count-cursor else { return nil }
      func point(_ at: Int) -> CGPoint { CGPoint(x: scalar(cursor+at*16), y: scalar(cursor+at*16+8)) }
      switch verb {
      case 1: current = point(0); result.move(to: current); drawn = false
      case 2:
        let end = point(0)
        if end != current { result.addLine(to: end); drawn = true }; current = end
      case 3:
        let control = point(0), end = point(1)
        if current != control || current != end { result.addQuadCurve(to: end, control: control); drawn = true }; current = end
      case 4:
        let first = point(0), second = point(1), end = point(2)
        if current != first || current != second || current != end { result.addCurve(to: end, control1: first, control2: second); drawn = true }; current = end
      default: if drawn { result.closeSubpath() }
      }
      cursor += count*8
    }
    guard cursor == bytes.count, let immutable = result.copy() else { return nil }
    path = immutable
  }
  func draw(_ context: CGContext, _ color: NSColor) {
    context.saveGState(); context.beginPath(); context.addPath(path)
    if flags & 1 != 0 {
      context.setStrokeColor(color.cgColor); context.setLineWidth(width); context.setMiterLimit(miter)
      context.setLineDash(phase: 0, lengths: [])
      context.setLineCap((flags >> 2) & 3 == 1 ? .round : (flags >> 2) & 3 == 2 ? .square : .butt)
      context.setLineJoin((flags >> 4) & 3 == 1 ? .round : (flags >> 4) & 3 == 2 ? .bevel : .miter)
      context.strokePath()
    } else { context.setFillColor(color.cgColor); context.drawPath(using: flags & 2 != 0 ? .eoFill : .fill) }
    context.restoreGState()
  }
}

private func decodeFrame(_ lease: UnsafeRawPointer, _ data: UnsafeRawPointer, _ len: UInt32,
                         _ background: NSColor, _ images: inout [UInt: WeakDrawImage]) -> ([DrawOp],NSColor)? {
    var next: [DrawOp] = []
    let count = data.load(fromByteOffset: 12, as: UInt32.self).littleEndian
    next.reserveCapacity(Int(count))
    var fill = NSColor.white, stroke = NSColor.white
    var width: CGFloat = 1
    var bg = background
    var stack: [(NSColor, NSColor, CGFloat)] = []
    var cursor: UInt32 = 32
    var values = [Double](repeating: 0, count: 8)
    var meta = [UInt32](repeating: 0, count: 2)
    var text: UnsafePointer<CChar>?
    var textLen: UInt32 = 0
    var imageID: UInt64 = 0
    func color(_ rgba: UInt32) -> NSColor {
      NSColor(srgbRed: CGFloat((rgba >> 24) & 255) / 255,
              green: CGFloat((rgba >> 16) & 255) / 255,
              blue: CGFloat((rgba >> 8) & 255) / 255, alpha: CGFloat(rgba & 255) / 255)
    }
    while cursor < len {
      let offset = cursor
      guard xuDrawNext(data, len, &cursor, &values, &meta, &text, &textLen, &imageID) == 1 else { return nil }
      let v = values
      let box = CGRect(x: v[0], y: v[1], width: v[2], height: v[3])
      switch meta[0] {
      case 1: bg = color(meta[1])
      case 2: fill = color(meta[1]); stroke = fill
      case 3: fill = color(meta[1])
      case 4: stroke = color(meta[1])
      case 5: width = CGFloat(v[0])
      case 6: stack.append((fill, stroke, width)); next.append(.push)
      case 7:
        guard let pen = stack.popLast() else { return nil }
        fill = pen.0; stroke = pen.1; width = pen.2; next.append(.pop)
      case 8: next.append(.origin)
      case 9: next.append(.translate(CGFloat(v[0]), CGFloat(v[1])))
      case 10: next.append(.rotate(CGFloat(v[0])))
      case 11: next.append(.scale(CGFloat(v[0]), CGFloat(v[1])))
      case 12: next.append(.clipRect(box))
      case 13: next.append(.fillRect(box, fill))
      case 14: next.append(.strokeRect(box, stroke, width))
      case 15: next.append(.fillRect(box, color(meta[1])))
      case 16: next.append(.strokeRect(box, color(meta[1]), CGFloat(v[4])))
      case 17: next.append(.line(CGPoint(x: v[0], y: v[1]), CGPoint(x: v[2], y: v[3]), color(meta[1]), CGFloat(v[4])))
      case 18:
        guard let text else { return nil }
        let bytes = UnsafeBufferPointer(start: UnsafeRawPointer(text).assumingMemoryBound(to: UInt8.self), count: Int(textLen))
        next.append(.text(CGPoint(x: v[0], y: v[1]), CGFloat(v[2]), color(meta[1]), String(decoding: bytes, as: UTF8.self)))
      case 19:
        next.append(.oval(CGRect(x: v[0] - v[2], y: v[1] - v[2], width: v[2] * 2, height: v[2] * 2), fill, nil, 1))
      case 20: next.append(.oval(box, fill, nil, 1))
      case 21: next.append(.triangle(CGPoint(x: v[0], y: v[1]), CGPoint(x: v[2], y: v[3]), CGPoint(x: v[4], y: v[5]), fill, nil, 1))
      case 22:
        guard let bitmap = xuFrameBitmap(lease, imageID) else { return nil }
        let key = UInt(bitPattern: bitmap)
        guard let image = images[key]?.value ?? DrawImage(bitmap) else { return nil }
        images[key] = WeakDrawImage(image)
        next.append(.image(image, box, CGRect(x: v[4], y: v[5], width: v[6], height: v[7]), meta[1]))
      case 23:
        guard let resource = xuFrameText(lease, imageID), let layout = DrawText(resource) else { return nil }
        next.append(.textLayout(layout, CGPoint(x: v[0], y: v[1]), color(meta[1])))
      case 25:
        guard let resource=xuFrameList(lease,imageID),let list=DrawDisplayList(resource) else {return nil}
        next.append(.displayList(list))
      case 24:
        var size: UInt32 = 0
        guard let payload = xuFramePath(lease, offset, &size), let path = DrawVectorPath(payload, size) else { return nil }
        next.append(.path(path, color(meta[1])))
      default: return nil
      }
    }
    guard stack.isEmpty else { return nil }
    return (next,bg)
}

private func paintDrawOps(_ displayOps: [DrawOp],_ ctx: CGContext) {
    ctx.saveGState()
    defer { ctx.restoreGState() }
    let viewBase = ctx.ctm
    var depth = 0
    for op in displayOps {
      switch op {
      case .push:
        ctx.saveGState()
        depth += 1
      case .pop:
        if depth > 0 { ctx.restoreGState(); depth -= 1 }
      case .origin:
        ctx.concatenate(ctx.ctm.inverted())
        ctx.concatenate(viewBase)
      case .translate(let dx, let dy):
        ctx.translateBy(x: dx, y: dy)
      case .rotate(let deg):
        ctx.rotate(by: deg * .pi / 180)
      case .scale(let sx, let sy):
        ctx.scaleBy(x: sx, y: sy)
      case .clipRect(let r):
        ctx.clip(to: r)
      case .textLayout(let layout, let origin, let color):
        layout.draw(ctx, origin, color)
      case .displayList(let list):
        list.draw(ctx)
      case .path(let path, let color):
        path.draw(ctx, color)
      case .image(let resource, let source, let destination, let flags):
        if destination.width <= 0 || destination.height <= 0 || flags & 65535 == 0 { break }
        ctx.saveGState()
        ctx.clip(to: destination)
        ctx.setAlpha(CGFloat(flags & 65535) / 65535)
        ctx.interpolationQuality = flags & 65536 == 0 ? .none : .low
        let sx = destination.width / source.width, sy = destination.height / source.height
        let image = resource.image
        ctx.translateBy(x: destination.minX - source.minX * sx,
                        y: destination.minY + (CGFloat(image.height) - source.minY) * sy)
        ctx.scaleBy(x: sx, y: -sy)
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        ctx.restoreGState()
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
    while depth > 0 { ctx.restoreGState(); depth -= 1 }
 }

enum DrawOp {
  case displayList(DrawDisplayList)
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
  case clipRect(CGRect)
  case image(DrawImage, CGRect, CGRect, UInt32)
  case textLayout(DrawText, CGPoint, NSColor)
  case path(DrawVectorPath, NSColor)
}

final class DrawCanvasView: NSView {
  var fillColor: NSColor = NSColor(calibratedWhite: 0.10, alpha: 1)
  var labelText: String = ""
  var ops: [DrawOp] = []
  var displayOps: [DrawOp] = []
  var displayColor: NSColor = NSColor(calibratedWhite: 0.10, alpha: 1)
  var displayLabel = ""
  var building = false
  var onClick: ((Int, Int) -> Void)?
  var onScroll: ((Int, Int) -> Void)?
  var onDrag: ((Int, Int) -> Void)?
  var lastDrag: NSPoint?
  var didPan = false
  var camX: CGFloat = 0 { didSet { textInputClient?.refresh() } }
  var camY: CGFloat = 0 { didSet { textInputClient?.refresh() } }
  var panEnabled = false
  var inputEnabled = false
  var inputButtons: UInt32 = 0
  var inputPoint: NSPoint?
  var onInput: ((String) -> Void)?
  var inputTracking: NSTrackingArea?
  var focusObserver: NSObjectProtocol?
  var focusGainObserver: NSObjectProtocol?
  var textInputID: UInt64 = 0
  var textInputClient: DrawInputClient?
  var cursorIndex = 0
  var windowID: UInt32 = 1
  var canvasID: UInt32 = 1
  var generation: UInt32 = 0
  var onMetrics: ((String) -> Void)?
  var lastMetrics = ""

  override var inputContext: NSTextInputContext? { textInputClient?.context }
  func blurTextInput() {
    guard let client = textInputClient else { return }
    textInputClient = nil; client.shutdown()
    _ = xuInputCancel(client.id)
  }
  func detachTextInput() { textInputID = 0; blurTextInput() }
  func focusTextInput() {
    guard textInputClient == nil, textInputID != 0, xuInputActive(textInputID) != 0,
          window?.firstResponder === self, window?.isKeyWindow == true else { return }
    let client = DrawInputClient(view: self, id: textInputID)
    textInputClient = client; client.context.activate(); client.refresh()
  }
  func startTextInput(_ id: UInt64) -> Bool {
    guard NativeInputState.read(id, canvasID, generation, take: true) != nil else { return false }
    let starting = id != textInputID
    if starting { detachTextInput(); textInputID = id }
    guard xuInputActivate(id, canvasID, generation) != 0 else { detachTextInput(); return true }
    if starting { window?.makeFirstResponder(self) }
    focusTextInput(); textInputClient?.refresh()
    return true
  }
  func pollTextInput() {
    if textInputID != 0 && xuInputActive(textInputID) == 0 { detachTextInput() }
    if window?.firstResponder !== self || window?.isKeyWindow != true { blurTextInput() }
    else { focusTextInput(); textInputClient?.refresh() }
  }

  func publishMetrics() {
    guard let window, let onMetrics, generation != 0 else { return }
    let backing = convertToBacking(bounds)
    let sx = bounds.width > 0 ? backing.width / bounds.width : window.backingScaleFactor
    let sy = bounds.height > 0 ? backing.height / bounds.height : window.backingScaleFactor
    let line = "canvas_metrics\t\(windowID)\t\(canvasID)\t\(generation)\t\(Double(bounds.width))\t\(Double(bounds.height))\t\(Int(ceil(backing.width)))\t\(Int(ceil(backing.height)))\t\(Double(sx))\t\(Double(sy))"
    if line != lastMetrics { lastMetrics = line; onMetrics(line) }
  }

  override func setFrameSize(_ size: NSSize) { super.setFrameSize(size); publishMetrics() }
  override func viewDidChangeBackingProperties() {
    super.viewDidChangeBackingProperties()
    publishMetrics(); needsDisplay = true
  }

  override func updateTrackingAreas() {
    super.updateTrackingAreas()
    if let inputTracking { removeTrackingArea(inputTracking) }
    let area = NSTrackingArea(rect: bounds, options: [.mouseMoved, .mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect], owner: self)
    addTrackingArea(area); inputTracking = area
  }
  override func viewDidMoveToWindow() {
    super.viewDidMoveToWindow()
    blurTextInput()
    if let focusObserver { NotificationCenter.default.removeObserver(focusObserver) }
    if let focusGainObserver { NotificationCenter.default.removeObserver(focusGainObserver) }
    focusObserver = nil
    focusGainObserver = nil
    window?.acceptsMouseMovedEvents = true
    if window == nil { cancelInput() }
    if let window {
      focusObserver = NotificationCenter.default.addObserver(forName: NSWindow.didResignKeyNotification,
        object: window, queue: .main) { [weak self] _ in self?.blurTextInput(); self?.cancelInput() }
      focusGainObserver = NotificationCenter.default.addObserver(forName: NSWindow.didBecomeKeyNotification,
        object: window, queue: .main) { [weak self] _ in self?.focusTextInput() }
    }
    publishMetrics()
  }
  deinit {
    textInputClient?.shutdown()
    if let focusObserver { NotificationCenter.default.removeObserver(focusObserver) }
    if let focusGainObserver { NotificationCenter.default.removeObserver(focusGainObserver) }
  }
  override func becomeFirstResponder() -> Bool {
    DispatchQueue.main.async { [weak self] in self?.focusTextInput() }
    return true
  }
  override func resignFirstResponder() -> Bool { blurTextInput(); cancelInput(); return true }
  override func resetCursorRects() {
    let cursors: [NSCursor] = [.arrow, .iBeam, .crosshair, .pointingHand, .resizeLeftRight, .resizeUpDown]
    addCursorRect(bounds, cursor: cursors[cursorIndex])
  }
  func inputModifiers(_ event: NSEvent) -> UInt32 {
    let flags = event.modifierFlags
    return (flags.contains(.shift) ? 1 : 0) | (flags.contains(.control) ? 2 : 0) |
           (flags.contains(.option) ? 4 : 0) | (flags.contains(.command) ? 8 : 0)
  }
  func emitInput(_ kind: Int, _ point: NSPoint = .zero, _ delta: NSPoint = .zero,
                 button: UInt32 = 0, modifiers: UInt32 = 0, key: UInt32 = 0,
                 scan: UInt32 = 0, repeated: Bool = false, clicks: Int = 0) {
    guard inputEnabled else { return }
    let stamp = Int64(ProcessInfo.processInfo.systemUptime * 1e9)
    let identity = generation == 0 ? "input\t\(kind)\t\(windowID)\t\(canvasID)" :
      "input2\t\(kind)\t\(windowID)\t\(canvasID)\t\(generation)"
    onInput?("\(identity)\t\(Double(point.x))\t\(Double(point.y))\t\(Double(delta.x))\t\(Double(delta.y))\t\(button)\t\(inputButtons)\t\(modifiers)\t\(key)\t\(scan)\t\(repeated ? 1 : 0)\t\(clicks)\t\(stamp)")
  }
  func cancelInput() {
    inputButtons = 0; inputPoint = nil; lastDrag = nil; didPan = true
    emitInput(77)
  }
  func pointerDown(_ event: NSEvent) {
    let button = UInt32(event.buttonNumber == 0 ? 1 : event.buttonNumber == 1 ? 2 : 3)
    inputButtons |= 1 << (button - 1)
    let p = convert(event.locationInWindow, from: nil)
    inputPoint = p
    emitInput(72, p, button: button, modifiers: inputModifiers(event), clicks: event.clickCount)
  }
  func pointerUp(_ event: NSEvent) {
    let button = UInt32(event.buttonNumber == 0 ? 1 : event.buttonNumber == 1 ? 2 : 3)
    inputButtons &= ~(1 << (button - 1))
    emitInput(73, convert(event.locationInWindow, from: nil), button: button, modifiers: inputModifiers(event))
  }
  override func mouseMoved(with event: NSEvent) {
    let p = convert(event.locationInWindow, from: nil)
    let previous = inputPoint ?? p
    emitInput(74, p, NSPoint(x: p.x - previous.x, y: p.y - previous.y), modifiers: inputModifiers(event))
    inputPoint = p
  }
  override func mouseEntered(with event: NSEvent) { emitInput(75, convert(event.locationInWindow, from: nil), modifiers: inputModifiers(event)) }
  override func mouseExited(with event: NSEvent) { emitInput(76, convert(event.locationInWindow, from: nil), modifiers: inputModifiers(event)) }
  override func rightMouseDown(with event: NSEvent) { window?.makeFirstResponder(self); pointerDown(event) }
  override func otherMouseDown(with event: NSEvent) { window?.makeFirstResponder(self); pointerDown(event) }
  override func rightMouseUp(with event: NSEvent) { pointerUp(event) }
  override func otherMouseUp(with event: NSEvent) { pointerUp(event) }
  override func rightMouseDragged(with event: NSEvent) { mouseMoved(with: event) }
  override func otherMouseDragged(with event: NSEvent) { mouseMoved(with: event) }
  func inputKey(_ event: NSEvent) -> UInt32 {
    switch event.keyCode {
    case 53: return 256; case 48: return 257; case 36, 76: return 258; case 51: return 259
    case 117: return 260; case 123: return 261; case 124: return 262; case 126: return 263
    case 125: return 264; case 115: return 265; case 119: return 266; case 116: return 267
    case 121: return 268; case 114: return 269
    case 122: return 288; case 120: return 289; case 99: return 290; case 118: return 291
    case 96: return 292; case 97: return 293; case 98: return 294; case 100: return 295
    case 101: return 296; case 109: return 297; case 103: return 298; case 111: return 299
    case 56, 60: return 304; case 59, 62: return 305; case 58, 61: return 306
    case 54, 55: return 307; case 57: return 308
    default:
      guard let scalar = event.charactersIgnoringModifiers?.uppercased().unicodeScalars.first else { return 0 }
      return scalar.value < 128 ? scalar.value : 0
    }
  }
  @objc override func selectAll(_ sender: Any?) {
    focusTextInput()
    if let client = textInputClient { client.doCommand(by: NSSelectorFromString("selectAll:")) }
    else { emitInput(78, modifiers: 8, key: 65) }
  }
  @objc func copy(_ sender: Any?) { emitInput(78, modifiers: 8, key: 67) }
  @objc func cut(_ sender: Any?) { emitInput(78, modifiers: 8, key: 88) }
  @objc func paste(_ sender: Any?) { emitInput(78, modifiers: 8, key: 86) }
  override func keyDown(with event: NSEvent) {
    emitInput(78, modifiers: inputModifiers(event), key: inputKey(event), scan: UInt32(event.keyCode), repeated: event.isARepeat)
    focusTextInput()
    if let client = textInputClient { _ = client.context.handleEvent(event) }
  }
  override func keyUp(with event: NSEvent) { emitInput(79, modifiers: inputModifiers(event), key: inputKey(event), scan: UInt32(event.keyCode)) }
  override func flagsChanged(with event: NSEvent) {
    let key = inputKey(event)
    let mask: NSEvent.ModifierFlags = key == 304 ? .shift : key == 305 ? .control : key == 306 ? .option : key == 307 ? .command : .capsLock
    emitInput(event.modifierFlags.contains(mask) ? 78 : 79, modifiers: inputModifiers(event), key: key, scan: UInt32(event.keyCode))
  }

  override var isFlipped: Bool { true }
  override var acceptsFirstResponder: Bool { true }
  override var mouseDownCanMoveWindow: Bool { false }

  func panBy(_ dx: CGFloat, _ dy: CGFloat) {
    if !panEnabled || (dx == 0 && dy == 0) { return }
    camX -= dx
    camY -= dy
    needsDisplay = true
  }

  override func draw(_ dirtyRect: NSRect) {
    displayColor.setFill()
    bounds.fill()
    if displayOps.isEmpty && !displayLabel.isEmpty {
      let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 22, weight: .semibold),
        .foregroundColor: NSColor.white,
      ]
      let size = displayLabel.size(withAttributes: attrs)
      let origin = NSPoint(
        x: (bounds.width - size.width) * 0.5,
        y: (bounds.height - size.height) * 0.5)
      displayLabel.draw(at: origin, withAttributes: attrs)
      return
    }
    guard let ctx = NSGraphicsContext.current?.cgContext else { return }
    ctx.saveGState()
    ctx.translateBy(x: -camX, y: -camY)
    paintDrawOps(displayOps,ctx)
    ctx.restoreGState()
  }

  override func mouseDown(with event: NSEvent) {
    window?.makeFirstResponder(self)
    pointerDown(event)
    let p = convert(event.locationInWindow, from: nil)
    lastDrag = p
    didPan = false
  }

  override func mouseDragged(with event: NSEvent) {
    mouseMoved(with: event)
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
    let wasDown = lastDrag != nil
    lastDrag = nil
    pointerUp(event)
    if wasDown && !didPan {
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
    // Raw scroll deltas move a content offset right/down, as on GTK/Win32.
    if dx != 0 || dy != 0 { emitInput(80, convert(event.locationInWindow, from: nil), NSPoint(x: -dx, y: -dy), modifiers: inputModifiers(event)) }
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
  var penStack: [(NSColor, NSColor, CGFloat)] = []
  var generation: UInt32 = 0
  var promptSheet: (id: UInt64, alert: NSAlert)?
  var images: [UInt: WeakDrawImage] = [:]

  init(shell: AppDelegate) {
    self.shell = shell
    super.init()
  }

  func resetPen() {
    penStack.removeAll(keepingCapacity: true)
    penFill = .white
    penStroke = .white
    penWidth = 1
  }

  func install(into root: NSView, host: AppDelegate) {
    shutdown()
    self.shell = host
    generation = host.canvasGeneration != 0 ? host.canvasGeneration : xuCanvasOpen(host.windowID, host.canvasID)
    guard generation != 0 else { return }
    let canvas = DrawCanvasView(frame: root.bounds)
    canvas.windowID = host.windowID; canvas.canvasID = host.canvasID; canvas.generation = generation
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
    canvas.onInput = { [weak self] line in self?.shell.appendShellFile(line) }
    root.addSubview(canvas)
    self.canvas = canvas
    host.appendShellFile("canvas_ready\t\(host.windowID)\t\(host.canvasID)\t\(generation)")
    canvas.onMetrics = { [weak self] line in self?.shell.appendShellFile(line) }
    canvas.publishMetrics()
  }

  func shutdown() {
    guard generation != 0 else { return }
    canvas?.detachTextInput()
    closePrompt()
    canvas?.cancelInput()
    canvas?.inputEnabled = false
    xuCanvasClose(canvas.canvasID, generation)
    shell?.appendShellFile("canvas_closed\t\(canvas.windowID)\t\(canvas.canvasID)\t\(generation)")
    generation = 0
    canvas?.ops.removeAll()
    canvas?.displayOps.removeAll()
    canvas?.onMetrics = nil; canvas?.onInput = nil; canvas?.generation = 0
    canvas?.removeFromSuperview()
    canvas = nil
  }

  deinit { shutdown() }

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

  // Frames arrive validated, owned and ordered with shell/content commands.
  func takeFrame(_ ticket: UInt64) -> Bool {
    var len: UInt32 = 0
    guard let canvas, generation != 0,
          let lease = xuDrawAcquire(ticket, canvas.canvasID, generation) else { return false }
    defer { xuFrameRelease(lease) }
    guard let data = xuFrameData(lease, &len) else { return false }
    images = images.filter { $0.value.value != nil }
    guard let scene = decodeFrame(lease, data, len, canvas.displayColor, &images) else { return false }
    let (next,bg) = scene
    canvas.displayOps = next
    canvas.displayColor = bg
    canvas.displayLabel = ""
    canvas.ops.removeAll(keepingCapacity: true)
    canvas.fillColor = bg; canvas.labelText = ""; canvas.building = false
    resetPen()
    canvas.needsDisplay = true
    return true
  }

  func handleCmd(_ s: String) -> Bool {
    guard canvas != nil, generation != 0 else { return false }
    if s.hasPrefix("__text_input\t") {
      let token = s.dropFirst(13)
      guard !token.isEmpty, token.utf8.allSatisfy({ $0 >= 48 && $0 <= 57 }),
            let id = UInt64(token), id > 0, id <= Int64.max else { return false }
      return canvas.startTextInput(id)
    }
    if s.hasPrefix("input_enabled\t") {
      if s.dropFirst(14) == "0" { canvas.cancelInput(); canvas.inputEnabled = false }
      else { canvas.inputEnabled = true; canvas.inputPoint = nil }
      return true
    }
    if s == "motion_preferences" {
      let reduced = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? 1 : 0
      shell.appendShellFile("canvas_preferences\t\(canvas.windowID)\t\(canvas.canvasID)\t\(generation)\t\(reduced)")
      return true
    }
    if s.hasPrefix("cursor\t") {
      guard let index = Int(s.dropFirst(7)), (0...5).contains(index) else { return false }
      canvas.cursorIndex = index
      canvas.window?.invalidateCursorRects(for: canvas)
      if let window = canvas.window, window.isKeyWindow,
         canvas.bounds.contains(canvas.convert(window.mouseLocationOutsideOfEventStream, from: nil)) {
        let cursors: [NSCursor] = [.arrow, .iBeam, .crosshair, .pointingHand, .resizeLeftRight, .resizeUpDown]
        cursors[index].set()
      }
      return true
    }
    if s.hasPrefix("__draw_frame\t") {
      guard let ticket = UInt64(s.dropFirst(13)) else { return false }
      return takeFrame(ticket)
    }
    if s.hasPrefix("__request\t"), let id = UInt64(s.dropFirst(10)) {
      return showPrompt(id)
    }
    if s.hasPrefix("pan_enabled\t") {
      canvas.panEnabled = String(s.dropFirst(12)) != "0"
      if !canvas.panEnabled {
        canvas.camX = 0
        canvas.camY = 0
      }
      canvas.needsDisplay = true
      return true
    }
    if s == "begin" {
      canvas.ops.removeAll(keepingCapacity: true)
      canvas.building = true
      resetPen()
      return true
    }
    if s == "present" {
      canvas.displayOps = canvas.ops
      canvas.displayColor = canvas.fillColor
      canvas.displayLabel = canvas.labelText
      canvas.building = false
      canvas.needsDisplay = true
      return true
    }
    if s == "cancel" {
      canvas.ops = canvas.displayOps
      canvas.fillColor = canvas.displayColor
      canvas.labelText = canvas.displayLabel
      canvas.building = false
      resetPen()
      return true
    }
    if s == "draw_clear" {
      canvas.fillColor = NSColor(calibratedWhite: 0.10, alpha: 1)
      canvas.labelText = ""
      canvas.ops.removeAll()
      canvas.displayOps.removeAll()
      canvas.displayColor = canvas.fillColor
      canvas.displayLabel = ""
      canvas.building = false
      resetPen()
      canvas.needsDisplay = true
      return true
    }
    if s == "push" {
      guard penStack.count < 256 else { return false }
      penStack.append((penFill, penStroke, penWidth))
      canvas.ops.append(.push)
      return true
    }
    if s == "pop" {
      guard let pen = penStack.popLast() else { return false }
      penFill = pen.0; penStroke = pen.1; penWidth = pen.2
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
        if !canvas.building {
          canvas.displayColor = c
          canvas.needsDisplay = true
        }
      }
      return true
    }
    if s.hasPrefix("label\t") {
      let parts = splitTabs(s, max: 1)
      if parts.count >= 2 {
        canvas.labelText = parts[1]
        if !canvas.building {
          canvas.displayLabel = parts[1]
          canvas.needsDisplay = true
        }
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
    if s.hasPrefix("clip_rect\t") {
      let p = splitTabs(s, max: 4)
      guard p.count == 5 else { return false }
      let r = rect5(p)
      guard r.width >= 0 && r.height >= 0 else { return false }
      canvas.ops.append(.clipRect(r))
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

  func onPoll() {
    xuTextInputPoll()
    canvas?.pollTextInput()
    xuRequestPoll()
    if let promptSheet, xuRequestAlive(promptSheet.id) == 0 { closePrompt() }
  }
  func syncFrame() {} // AppKit invalidates resize/expose; present invalidates content.

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

  func closePrompt() {
    guard let sheet = promptSheet else { return }
    promptSheet = nil
    completeRequest(sheet.id, 1)
    sheet.alert.window.sheetParent?.endSheet(sheet.alert.window, returnCode: .cancel)
    sheet.alert.window.orderOut(nil)
  }

  func showPrompt(_ id: UInt64) -> Bool {
    guard let canvas, let wire = xuRequestTake(id, canvas.canvasID, generation) else { return false }
    let fields = String(cString: wire).split(separator: "\t", omittingEmptySubsequences: false)
    free(wire)
    guard fields.count == 9, fields[4] == "1", let title = requestText(fields[7]), let seed = requestText(fields[8]),
          let window = canvas.window else { completeRequest(id, 2, "prompt owner is unavailable"); return true }
    closePrompt()
    let alert = NSAlert()
    alert.messageText = title.isEmpty ? "Xu" : title
    alert.addButton(withTitle: "OK"); alert.addButton(withTitle: "Cancel")
    let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
    field.stringValue = seed; alert.accessoryView = field; alert.window.initialFirstResponder = field
    promptSheet = (id, alert)
    alert.beginSheetModal(for: window) { [weak self] response in
      completeRequest(id, response == .alertFirstButtonReturn ? 0 : 1,
                      response == .alertFirstButtonReturn ? field.stringValue : "")
      if self?.promptSheet?.id == id { self?.promptSheet = nil }
    }
    return true
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
    XuContentRegistry.factories[2] = XuContentRegistry.make
  }
}
