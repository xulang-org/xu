#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>
#include "native/host/phone/phone.h"

@interface XuTextPosition : UITextPosition
@property (nonatomic, assign) NSUInteger offset;
+ (instancetype)positionWithOffset:(NSUInteger)offset;
@end

@implementation XuTextPosition
+ (instancetype)positionWithOffset:(NSUInteger)offset {
  XuTextPosition *pos = [XuTextPosition new];
  pos.offset = offset;
  return pos;
}
@end

@interface XuTextRange : UITextRange
@property (nonatomic, assign) NSUInteger startOffset;
@property (nonatomic, assign) NSUInteger endOffset;
+ (instancetype)rangeWithStart:(NSUInteger)start end:(NSUInteger)end;
- (NSRange)nsRange;
@end

@implementation XuTextRange
+ (instancetype)rangeWithStart:(NSUInteger)start end:(NSUInteger)end {
  XuTextRange *range = [XuTextRange new];
  range.startOffset = MIN(start, end);
  range.endOffset = MAX(start, end);
  return range;
}
- (UITextPosition *)start { return [XuTextPosition positionWithOffset:self.startOffset]; }
- (UITextPosition *)end { return [XuTextPosition positionWithOffset:self.endOffset]; }
- (BOOL)isEmpty { return self.startOffset == self.endOffset; }
- (NSRange)nsRange { return NSMakeRange(self.startOffset, self.endOffset - self.startOffset); }
@end

@interface XuTextInputView : UIView <UITextInput, UITextInputTraits>
@property (nonatomic, assign) BOOL sessionActive;
@property (nonatomic, assign) uint64_t sessionId;
@property (nonatomic, assign) uint64_t revision;
@property (nonatomic, assign) BOOL multiline;
@property (nonatomic, assign) BOOL secureEntry;
@property (nonatomic, copy) NSString *displayText;
@property (nonatomic, assign) NSRange selectedRange16;
@property (nonatomic, assign) NSRange markedRange16;
@property (nonatomic, assign) CGRect caretRect16;
@property (nonatomic, strong) id<UITextInputTokenizer> xuTokenizer;
@property (nonatomic, weak) id<UITextInputDelegate> inputDelegate;
@property (nonatomic, copy) NSDictionary<NSAttributedStringKey, id> *markedTextStyle;
@end

@implementation XuTextInputView
- (instancetype)initWithFrame:(CGRect)frame {
  self = [super initWithFrame:frame];
  if (self) {
    _displayText = @"";
    _selectedRange16 = NSMakeRange(0, 0);
    _markedRange16 = NSMakeRange(NSNotFound, 0);
    _caretRect16 = CGRectMake(20, 120, 2, 24);
    self.backgroundColor = UIColor.clearColor;
    self.opaque = NO;
  }
  return self;
}
- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event {
  return nil;
}
- (BOOL)canBecomeFirstResponder {
  return self.sessionActive;
}
- (id<UITextInputTokenizer>)tokenizer {
  if (!self.xuTokenizer) {
    self.xuTokenizer = [[UITextInputStringTokenizer alloc] initWithTextInput:self];
  }
  return self.xuTokenizer;
}
- (NSUInteger)clampOffset:(NSInteger)offset {
  NSInteger len = (NSInteger)self.displayText.length;
  if (offset < 0) return 0;
  if (offset > len) return (NSUInteger)len;
  return (NSUInteger)offset;
}
- (NSRange)clampRange:(NSRange)r {
  NSUInteger len = self.displayText.length;
  if (r.location == NSNotFound) return NSMakeRange(NSNotFound, 0);
  NSUInteger loc = MIN(r.location, len);
  NSUInteger end = MIN(r.location + r.length, len);
  return NSMakeRange(loc, end - loc);
}
- (void)applyStateDict:(NSDictionary *)dict notifyDelegate:(BOOL)notify {
  if (![dict isKindOfClass:NSDictionary.class] || ![dict[@"active"] boolValue]) {
    [self clearSessionAndNotify:notify];
    return;
  }
  uint64_t nextId = [dict[@"id"] unsignedLongLongValue];
  uint64_t nextRev = [dict[@"revision"] unsignedLongLongValue];
  BOOL nextMultiline = [dict[@"multiline"] boolValue];
  BOOL nextPassword = [dict[@"password"] boolValue];
  BOOL composing = [dict[@"composing"] boolValue];
  NSString *nextDisplay = [dict[@"display"] isKindOfClass:NSString.class] ? dict[@"display"] : @"";
  NSInteger a16 = [dict[@"display_anchor16"] integerValue];
  NSInteger f16 = [dict[@"display_focus16"] integerValue];
  NSUInteger len = nextDisplay.length;
  NSUInteger lo = (NSUInteger)MAX(0, MIN(MIN(a16, f16), (NSInteger)len));
  NSUInteger hi = (NSUInteger)MAX(0, MIN(MAX(a16, f16), (NSInteger)len));
  NSRange nextSel = NSMakeRange(lo, hi - lo);
  NSRange nextMarked = NSMakeRange(NSNotFound, 0);
  if (composing) {
    NSInteger s16 = MAX(0, [dict[@"start16"] integerValue]);
    NSString *pre = [dict[@"preedit"] isKindOfClass:NSString.class] ? dict[@"preedit"] : @"";
    NSUInteger ms = MIN((NSUInteger)s16, len);
    NSUInteger ml = MIN(pre.length, len - ms);
    nextMarked = NSMakeRange(ms, ml);
  }
  NSArray *caretArr = [dict[@"caret"] isKindOfClass:NSArray.class] ? dict[@"caret"] : nil;
  CGRect nextCaret = self.caretRect16;
  if (caretArr.count == 4) {
    nextCaret = CGRectMake([caretArr[0] doubleValue], [caretArr[1] doubleValue],
                           MAX(2.0, [caretArr[2] doubleValue]), MAX(20.0, [caretArr[3] doubleValue]));
  }
  BOOL changed = (!self.sessionActive || self.sessionId != nextId ||
                  ![self.displayText isEqualToString:nextDisplay] ||
                  !NSEqualRanges(self.selectedRange16, nextSel) ||
                  !NSEqualRanges(self.markedRange16, nextMarked));
  if (notify && changed) {
    [self.inputDelegate selectionWillChange:self];
    [self.inputDelegate textWillChange:self];
  }
  self.sessionActive = YES;
  self.sessionId = nextId;
  self.revision = nextRev;
  self.multiline = nextMultiline;
  self.secureEntry = nextPassword;
  self.displayText = nextDisplay;
  self.selectedRange16 = nextSel;
  self.markedRange16 = nextMarked;
  self.caretRect16 = nextCaret;
  if (notify && changed) {
    [self.inputDelegate textDidChange:self];
    [self.inputDelegate selectionDidChange:self];
  }
}
- (void)clearSessionAndNotify:(BOOL)notify {
  if (!self.sessionActive && self.displayText.length == 0) return;
  if (notify) {
    [self.inputDelegate selectionWillChange:self];
    [self.inputDelegate textWillChange:self];
  }
  self.sessionActive = NO;
  self.sessionId = 0;
  self.revision = 0;
  self.displayText = @"";
  self.selectedRange16 = NSMakeRange(0, 0);
  self.markedRange16 = NSMakeRange(NSNotFound, 0);
  if (notify) {
    [self.inputDelegate textDidChange:self];
    [self.inputDelegate selectionDidChange:self];
  }
}
- (void)refreshFromHost {
  char *raw = xu_phone_text_input_state();
  if (!raw) return;
  NSData *data = [NSData dataWithBytes:raw length:strlen(raw)];
  free(raw);
  NSDictionary *dict = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
  [self applyStateDict:dict notifyDelegate:NO];
}
#pragma mark - UITextInputTraits
- (UIKeyboardType)keyboardType { return UIKeyboardTypeDefault; }
- (UIReturnKeyType)returnKeyType { return self.multiline ? UIReturnKeyDefault : UIReturnKeyDone; }
- (BOOL)isSecureTextEntry { return self.secureEntry; }
- (UITextAutocorrectionType)autocorrectionType {
  return self.secureEntry ? UITextAutocorrectionTypeNo : UITextAutocorrectionTypeDefault;
}
#pragma mark - UIKeyInput
- (BOOL)hasText { return self.displayText.length > 0; }
- (void)insertText:(NSString *)text {
  if (!self.sessionActive) return;
  NSString *value = text ?: @"";
  if (!self.multiline && [value isEqualToString:@"\n"]) {
    xu_phone_key(78, 258, 0, 0);
    xu_phone_key(79, 258, 0, 0);
    [self refreshFromHost];
    return;
  }
  NSData *utf8 = [value dataUsingEncoding:NSUTF8StringEncoding];
  xu_phone_text_input_commit(self.sessionId, 0, (const char *)utf8.bytes, (unsigned)utf8.length);
  [self refreshFromHost];
}
- (void)deleteBackward {
  if (!self.sessionActive) return;
  xu_phone_text_input_erase(self.sessionId, 0, 1);
  [self refreshFromHost];
}
#pragma mark - UITextInput
- (NSString *)textInRange:(UITextRange *)range {
  if (![range isKindOfClass:XuTextRange.class]) return @"";
  NSRange r = [self clampRange:[(XuTextRange *)range nsRange]];
  if (r.location == NSNotFound) return @"";
  return [self.displayText substringWithRange:r];
}
- (void)replaceRange:(UITextRange *)range withText:(NSString *)text {
  if (!self.sessionActive || ![range isKindOfClass:XuTextRange.class]) return;
  NSRange r = [self clampRange:[(XuTextRange *)range nsRange]];
  if (r.location == NSNotFound) return;
  NSString *value = text ?: @"";
  NSData *utf8 = [value dataUsingEncoding:NSUTF8StringEncoding];
  xu_phone_text_input_replace(self.sessionId, 0, (unsigned)r.location, (unsigned)NSMaxRange(r),
                              (const char *)utf8.bytes, (unsigned)utf8.length);
  [self refreshFromHost];
}
- (UITextRange *)selectedTextRange {
  if (!self.sessionActive) return nil;
  return [XuTextRange rangeWithStart:self.selectedRange16.location end:NSMaxRange(self.selectedRange16)];
}
- (void)setSelectedTextRange:(UITextRange *)selectedTextRange {
  if (!self.sessionActive || ![selectedTextRange isKindOfClass:XuTextRange.class]) return;
  NSRange r = [self clampRange:[(XuTextRange *)selectedTextRange nsRange]];
  if (r.location == NSNotFound) return;
  xu_phone_text_input_select(self.sessionId, 0, (unsigned)r.location, (unsigned)NSMaxRange(r));
  [self refreshFromHost];
}
- (UITextRange *)markedTextRange {
  if (!self.sessionActive || self.markedRange16.location == NSNotFound) return nil;
  return [XuTextRange rangeWithStart:self.markedRange16.location end:NSMaxRange(self.markedRange16)];
}
- (void)setMarkedText:(NSString *)markedText selectedRange:(NSRange)selectedRange {
  if (!self.sessionActive) return;
  NSString *pre = markedText ?: @"";
  NSUInteger a = MIN(selectedRange.location, pre.length);
  NSUInteger f = MIN(selectedRange.location + selectedRange.length, pre.length);
  NSData *utf8 = [pre dataUsingEncoding:NSUTF8StringEncoding];
  xu_phone_text_input_compose(self.sessionId, 0, (const char *)utf8.bytes, (unsigned)utf8.length,
                              (unsigned)a, (unsigned)f);
  [self refreshFromHost];
}
- (void)unmarkText {
  if (!self.sessionActive) return;
  xu_phone_text_input_finish_composing(self.sessionId, 0);
  [self refreshFromHost];
}
- (UITextPosition *)beginningOfDocument { return [XuTextPosition positionWithOffset:0]; }
- (UITextPosition *)endOfDocument { return [XuTextPosition positionWithOffset:self.displayText.length]; }
- (UITextRange *)textRangeFromPosition:(UITextPosition *)fromPosition toPosition:(UITextPosition *)toPosition {
  if (![fromPosition isKindOfClass:XuTextPosition.class] || ![toPosition isKindOfClass:XuTextPosition.class]) return nil;
  NSUInteger a = [self clampOffset:((XuTextPosition *)fromPosition).offset];
  NSUInteger b = [self clampOffset:((XuTextPosition *)toPosition).offset];
  return [XuTextRange rangeWithStart:a end:b];
}
- (UITextPosition *)positionFromPosition:(UITextPosition *)position offset:(NSInteger)offset {
  if (![position isKindOfClass:XuTextPosition.class]) return nil;
  NSInteger next = (NSInteger)((XuTextPosition *)position).offset + offset;
  if (next < 0 || next > (NSInteger)self.displayText.length) return nil;
  return [XuTextPosition positionWithOffset:(NSUInteger)next];
}
- (UITextPosition *)positionFromPosition:(UITextPosition *)position inDirection:(UITextLayoutDirection)direction offset:(NSInteger)offset {
  NSInteger delta = (direction == UITextLayoutDirectionLeft || direction == UITextLayoutDirectionUp) ? -offset : offset;
  return [self positionFromPosition:position offset:delta];
}
- (NSComparisonResult)comparePosition:(UITextPosition *)position toPosition:(UITextPosition *)other {
  NSUInteger a = [position isKindOfClass:XuTextPosition.class] ? ((XuTextPosition *)position).offset : 0;
  NSUInteger b = [other isKindOfClass:XuTextPosition.class] ? ((XuTextPosition *)other).offset : 0;
  if (a < b) return NSOrderedAscending;
  if (a > b) return NSOrderedDescending;
  return NSOrderedSame;
}
- (NSInteger)offsetFromPosition:(UITextPosition *)from toPosition:(UITextPosition *)toPosition {
  NSInteger a = [from isKindOfClass:XuTextPosition.class] ? (NSInteger)((XuTextPosition *)from).offset : 0;
  NSInteger b = [toPosition isKindOfClass:XuTextPosition.class] ? (NSInteger)((XuTextPosition *)toPosition).offset : 0;
  return b - a;
}
- (UITextPosition *)positionWithinRange:(UITextRange *)range farthestInDirection:(UITextLayoutDirection)direction {
  if (![range isKindOfClass:XuTextRange.class]) return nil;
  XuTextRange *r = (XuTextRange *)range;
  BOOL backward = (direction == UITextLayoutDirectionLeft || direction == UITextLayoutDirectionUp);
  return [XuTextPosition positionWithOffset:backward ? r.startOffset : r.endOffset];
}
- (UITextRange *)characterRangeByExtendingPosition:(UITextPosition *)position inDirection:(UITextLayoutDirection)direction {
  if (![position isKindOfClass:XuTextPosition.class]) return nil;
  NSUInteger off = [self clampOffset:((XuTextPosition *)position).offset];
  if (direction == UITextLayoutDirectionLeft || direction == UITextLayoutDirectionUp) {
    return [XuTextRange rangeWithStart:0 end:off];
  }
  return [XuTextRange rangeWithStart:off end:self.displayText.length];
}
- (NSWritingDirection)baseWritingDirectionForPosition:(UITextPosition *)position inDirection:(UITextStorageDirection)direction {
  return NSWritingDirectionNatural;
}
- (void)setBaseWritingDirection:(NSWritingDirection)writingDirection forRange:(UITextRange *)range {}
- (CGRect)firstRectForRange:(UITextRange *)range {
  return self.bounds;
}
- (CGRect)caretRectForPosition:(UITextPosition *)position {
  return CGRectMake(0, 0, MAX(2.0, self.bounds.size.width), MAX(20.0, self.bounds.size.height));
}
- (NSArray<UITextSelectionRect *> *)selectionRectsForRange:(UITextRange *)range {
  return @[];
}
- (UITextPosition *)closestPositionToPoint:(CGPoint)point {
  return [XuTextPosition positionWithOffset:self.selectedRange16.location];
}
- (UITextPosition *)closestPositionToPoint:(CGPoint)point withinRange:(UITextRange *)range {
  return [self closestPositionToPoint:point];
}
- (UITextRange *)characterRangeAtPoint:(CGPoint)point {
  NSUInteger loc = self.selectedRange16.location;
  return [XuTextRange rangeWithStart:loc end:loc];
}
- (void)pressesBegan:(NSSet<UIPress *> *)presses withEvent:(UIPressesEvent *)event {
  if (self.sessionActive) {
    for (UIPress *press in presses) {
      UIKey *key = press.key;
      if (!key) continue;
      BOOL shift = (key.modifierFlags & UIKeyModifierShift) != 0;
      switch (key.keyCode) {
        case UIKeyboardHIDUsageKeyboardEscape:
          xu_phone_back();
          return;
        case UIKeyboardHIDUsageKeyboardLeftArrow:
          xu_phone_text_input_move(self.sessionId, 0, 1, shift ? 1 : 0);
          [self refreshFromHost];
          return;
        case UIKeyboardHIDUsageKeyboardRightArrow:
          xu_phone_text_input_move(self.sessionId, 0, 0, shift ? 1 : 0);
          [self refreshFromHost];
          return;
        case UIKeyboardHIDUsageKeyboardHome:
          xu_phone_text_input_select(self.sessionId, 0, shift ? (unsigned)self.selectedRange16.location : 0, 0);
          [self refreshFromHost];
          return;
        case UIKeyboardHIDUsageKeyboardEnd:
          xu_phone_text_input_select(self.sessionId, 0,
                                     shift ? (unsigned)self.selectedRange16.location : (unsigned)self.displayText.length,
                                     (unsigned)self.displayText.length);
          [self refreshFromHost];
          return;
        case UIKeyboardHIDUsageKeyboardDeleteForward:
          xu_phone_text_input_erase(self.sessionId, 0, 0);
          [self refreshFromHost];
          return;
        default:
          break;
      }
    }
  }
  [super pressesBegan:presses withEvent:event];
}
@end

@interface XuController : UIViewController <WKScriptMessageHandler, WKNavigationDelegate>
@property WKWebView *web;
@property XuTextInputView *textInputView;
@property CADisplayLink *display;
@property BOOL evaluating;
@property BOOL darkAppearance;
@property BOOL overlayVisible;
@property BOOL imeVisible;
@property CGFloat imeBottom;
@end
@implementation XuController
- (void)syncInsets {
  UIEdgeInsets safe = self.view.safeAreaInsets;
  xu_phone_insets(safe.top, safe.bottom, safe.left, safe.right, self.imeBottom);
}
- (void)syncMotion {
  xu_phone_reduced_motion(UIAccessibilityIsReduceMotionEnabled() ? 1 : 0);
}
- (void)keyboardChanged:(NSNotification *)note {
  CGRect endFrame = [note.userInfo[UIKeyboardFrameEndUserInfoKey] CGRectValue];
  CGRect local = [self.view convertRect:endFrame fromView:nil];
  CGRect overlap = CGRectIntersection(self.view.bounds, local);
  self.imeBottom = (CGRectIsNull(overlap) || CGRectIsEmpty(overlap)) ? 0.0
    : fmax(0.0, CGRectGetMaxY(self.view.bounds) - CGRectGetMinY(overlap));
  if (self.imeBottom > 0.0) self.imeVisible = YES;
  [self syncInsets];
}
- (void)keyboardHidden:(NSNotification *)note {
  BOOL wasVisible = self.imeVisible;
  self.imeVisible = NO;
  self.imeBottom = 0.0;
  [self syncInsets];
  if (wasVisible && self.textInputView.sessionActive) {
    xu_phone_text_input_stop(self.textInputView.sessionId);
    [self.textInputView clearSessionAndNotify:YES];
    [self.textInputView resignFirstResponder];
  }
}
- (void)reduceMotionChanged:(NSNotification *)note {
  [self syncMotion];
}
- (void)dealloc {
  [NSNotificationCenter.defaultCenter removeObserver:self];
}
- (void)loadView {
  self.view = [UIView new];
  self.view.backgroundColor = [UIColor colorWithRed:246.0/255 green:243.0/255 blue:239.0/255 alpha:1];
  WKWebViewConfiguration *config = [WKWebViewConfiguration new];
  [config.userContentController addScriptMessageHandler:self name:@"xu"];
  self.web = [[WKWebView alloc] initWithFrame:CGRectZero configuration:config];
  self.web.scrollView.scrollEnabled = NO;
  self.web.scrollView.contentInsetAdjustmentBehavior = UIScrollViewContentInsetAdjustmentNever;
  self.web.opaque = NO;
  self.web.backgroundColor = UIColor.clearColor;
  self.web.navigationDelegate = self;
  self.web.translatesAutoresizingMaskIntoConstraints = NO;
  [self.view addSubview:self.web];
  [NSLayoutConstraint activateConstraints:@[
    [self.web.topAnchor constraintEqualToAnchor:self.view.topAnchor],
    [self.web.bottomAnchor constraintEqualToAnchor:self.view.bottomAnchor],
    [self.web.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor],
    [self.web.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor]
  ]];
  self.textInputView = [[XuTextInputView alloc] initWithFrame:CGRectMake(20, 120, 2, 24)];
  [self.view addSubview:self.textInputView];
  NSNotificationCenter *nc = NSNotificationCenter.defaultCenter;
  [nc addObserver:self selector:@selector(keyboardChanged:) name:UIKeyboardWillChangeFrameNotification object:nil];
  [nc addObserver:self selector:@selector(keyboardHidden:) name:UIKeyboardWillHideNotification object:nil];
  [nc addObserver:self selector:@selector(reduceMotionChanged:) name:UIAccessibilityReduceMotionStatusDidChangeNotification object:nil];
  [self syncMotion];
  NSURL *url = [NSBundle.mainBundle URLForResource:@"canvas" withExtension:@"html"];
  [self.web loadFileURL:url allowingReadAccessToURL:url];
  self.display = [CADisplayLink displayLinkWithTarget:self selector:@selector(tick)];
  [self.display addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
}
- (void)viewSafeAreaInsetsDidChange {
  [super viewSafeAreaInsetsDidChange];
  [self syncInsets];
}
- (void)viewDidLayoutSubviews {
  [super viewDidLayoutSubviews];
  [self syncInsets];
}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
  if (!message.frameInfo.mainFrame || ![message.body isKindOfClass:NSString.class]) return;
  NSData *data = [(NSString *)message.body dataUsingEncoding:NSUTF8StringEncoding];
  NSArray *v = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
  if (![v isKindOfClass:NSArray.class] || v.count != 7) return;
  for (id value in v) if (![value isKindOfClass:NSNumber.class]) return;
  int kind = [v[0] intValue];
  if (kind == 1) xu_phone_start("ios");
  else if (kind == 0) xu_phone_resize([v[4] doubleValue],[v[5] doubleValue],[v[6] doubleValue]);
  else xu_phone_input(kind,[v[1] doubleValue],[v[2] doubleValue],[v[3] intValue]);
}
- (UIStatusBarStyle)preferredStatusBarStyle {
  return self.darkAppearance ? UIStatusBarStyleLightContent : UIStatusBarStyleDarkContent;
}
- (void)syncTextInput {
  char *raw = xu_phone_text_input_state();
  if (!raw) return;
  NSData *data = [NSData dataWithBytes:raw length:strlen(raw)];
  free(raw);
  NSDictionary *dict = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
  [self.textInputView applyStateDict:dict notifyDelegate:YES];
  if (self.textInputView.sessionActive) {
    CGRect caret = self.textInputView.caretRect16;
    CGFloat maxW = MAX(2.0, self.view.bounds.size.width);
    CGFloat maxH = MAX(20.0, self.view.bounds.size.height);
    CGFloat cx = fmin(fmax(0.0, caret.origin.x), maxW - 2.0);
    CGFloat cy = fmin(fmax(0.0, caret.origin.y), maxH - 20.0);
    self.textInputView.frame = CGRectMake(cx, cy, fmin(caret.size.width, maxW - cx), fmin(caret.size.height, maxH - cy));
    if (!self.textInputView.isFirstResponder) {
      [self.textInputView becomeFirstResponder];
    }
  } else {
    if (self.textInputView.isFirstResponder) {
      [self.textInputView resignFirstResponder];
    }
  }
}
- (void)tick {
  BOOL dark = xu_phone_dark() != 0, overlay = xu_phone_overlay() != 0;
  if (dark != self.darkAppearance || overlay != self.overlayVisible) {
    self.darkAppearance = dark; self.overlayVisible = overlay;
    self.overrideUserInterfaceStyle = dark ? UIUserInterfaceStyleDark : UIUserInterfaceStyleLight;
    self.view.backgroundColor = dark
      ? [UIColor colorWithRed:16.0/255 green:14.0/255 blue:18.0/255 alpha:1]
      : [UIColor colorWithRed:246.0/255 green:243.0/255 blue:239.0/255 alpha:1];
    [self setNeedsStatusBarAppearanceUpdate];
  }
  [self syncTextInput];
  if (self.evaluating) return;
  char *frame = xu_phone_poll(); if (!frame) return;
  NSString *json = [[NSString alloc] initWithUTF8String:frame]; free(frame);
  self.evaluating = YES;
  [self.web evaluateJavaScript:[@"xuFrame(" stringByAppendingFormat:@"%@)",json] completionHandler:^(id result,NSError *error){
    self.evaluating = NO;
    if (error) NSLog(@"Xu Phone render: %@",error);
  }];
}
- (void)webView:(WKWebView *)web decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decision {
  decision(action.request.URL.isFileURL ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}
@end
@interface XuScene : UIResponder <UIWindowSceneDelegate>
@property (nonatomic, strong) UIWindow *window;
@end
@implementation XuScene
- (void)scene:(UIScene *)scene willConnectToSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
  self.window = [[UIWindow alloc] initWithWindowScene:(UIWindowScene *)scene];
  self.window.rootViewController = [XuController new]; [self.window makeKeyAndVisible];
}
- (void)sceneDidBecomeActive:(UIScene *)scene { xu_phone_active(1); }
- (void)sceneWillResignActive:(UIScene *)scene { xu_phone_active(0); }
@end
@interface XuApp : UIResponder <UIApplicationDelegate>
@end
@implementation XuApp
@end
int main(int argc,char **argv) {
  @autoreleasepool { return UIApplicationMain(argc,argv,nil,NSStringFromClass(XuApp.class)); }
}
