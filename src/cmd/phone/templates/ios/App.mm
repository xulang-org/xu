#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>
#include "native/host/phone/phone.h"

@interface XuController : UIViewController <WKScriptMessageHandler, WKNavigationDelegate>
@property WKWebView *web;
@property CADisplayLink *display;
@property BOOL evaluating;
@property BOOL darkAppearance;
@property BOOL overlayVisible;
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
  [self syncInsets];
}
- (void)keyboardHidden:(NSNotification *)note {
  self.imeBottom = 0.0;
  [self syncInsets];
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
