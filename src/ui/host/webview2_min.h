// Auto-trimmed WebView2 COM decls for mingw (no NuGet SDK required).
// IIDs/vtables match Microsoft.Web.WebView2 1.0.2210.55.
#pragma once
#ifndef WEBVIEW2_MIN_H
#define WEBVIEW2_MIN_H

#include <windows.h>
#include <objbase.h>
#include <objidl.h>
#include <stdint.h>

#ifdef __cplusplus

#ifndef __EventRegistrationToken_DEFINED
#define __EventRegistrationToken_DEFINED
typedef struct EventRegistrationToken { int64_t value; } EventRegistrationToken;
#endif

typedef struct COREWEBVIEW2_COLOR { BYTE A; BYTE R; BYTE G; BYTE B; } COREWEBVIEW2_COLOR;
typedef enum COREWEBVIEW2_MOVE_FOCUS_REASON {
  COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC = 0,
  COREWEBVIEW2_MOVE_FOCUS_REASON_NEXT = 1,
  COREWEBVIEW2_MOVE_FOCUS_REASON_PREVIOUS = 2
} COREWEBVIEW2_MOVE_FOCUS_REASON;
typedef enum COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT {
  COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG = 0,
  COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_JPEG = 1
} COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT;
typedef enum COREWEBVIEW2_WEB_RESOURCE_CONTEXT {
  COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL = 0
} COREWEBVIEW2_WEB_RESOURCE_CONTEXT;
typedef enum COREWEBVIEW2_WEB_ERROR_STATUS {
  COREWEBVIEW2_WEB_ERROR_STATUS_UNKNOWN = 0
} COREWEBVIEW2_WEB_ERROR_STATUS;
typedef enum COREWEBVIEW2_COOKIE_SAME_SITE_KIND {
  COREWEBVIEW2_COOKIE_SAME_SITE_KIND_NONE = 0,
  COREWEBVIEW2_COOKIE_SAME_SITE_KIND_LAX = 1,
  COREWEBVIEW2_COOKIE_SAME_SITE_KIND_STRICT = 2
} COREWEBVIEW2_COOKIE_SAME_SITE_KIND;

// Opaque forwards for types we only pass as pointers.
struct ICoreWebView2HttpRequestHeaders;
struct ICoreWebView2HttpResponseHeaders;
struct ICoreWebView2Deferral;
struct ICoreWebView2WindowFeatures;
struct ICoreWebView2AcceleratorKeyPressedEventHandler;
struct ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler;
struct ICoreWebView2CallDevToolsProtocolMethodCompletedHandler;
struct ICoreWebView2CapturePreviewCompletedHandler;
struct ICoreWebView2ContainsFullScreenElementChangedEventHandler;
struct ICoreWebView2ContentLoadingEventHandler;
struct ICoreWebView2DOMContentLoadedEventHandler;
struct ICoreWebView2DevToolsProtocolEventReceiver;
struct ICoreWebView2DocumentTitleChangedEventHandler;
struct ICoreWebView2EnvironmentOptions;
struct ICoreWebView2EnvironmentOptions4;
struct ICoreWebView2CustomSchemeRegistration;
struct ICoreWebView2FocusChangedEventHandler;
struct ICoreWebView2HistoryChangedEventHandler;
struct ICoreWebView2MoveFocusRequestedEventHandler;
struct ICoreWebView2NewBrowserVersionAvailableEventHandler;
struct ICoreWebView2PermissionRequestedEventHandler;
struct ICoreWebView2ProcessFailedEventHandler;
struct ICoreWebView2ScriptDialogOpeningEventHandler;
struct ICoreWebView2SourceChangedEventHandler;
struct ICoreWebView2WebMessageReceivedEventHandler;
struct ICoreWebView2WebResourceRequest;
struct ICoreWebView2WebResourceRequestedEventHandler;
struct ICoreWebView2WebResourceRequestedEventArgs;
struct ICoreWebView2WebResourceResponse;
struct ICoreWebView2WebResourceResponseReceivedEventHandler;
struct ICoreWebView2WindowCloseRequestedEventHandler;
struct ICoreWebView2ZoomFactorChangedEventHandler;
struct IStream;

struct ICoreWebView2;
struct ICoreWebView2_2;
struct ICoreWebView2Controller;
struct ICoreWebView2Controller2;
struct ICoreWebView2Environment;
struct ICoreWebView2Settings;
struct ICoreWebView2Settings2;
struct ICoreWebView2CookieManager;
struct ICoreWebView2Cookie;
struct ICoreWebView2CookieList;
struct ICoreWebView2NavigationStartingEventArgs;
struct ICoreWebView2NavigationCompletedEventArgs;
struct ICoreWebView2NewWindowRequestedEventArgs;
struct ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler;
struct ICoreWebView2CreateCoreWebView2ControllerCompletedHandler;
struct ICoreWebView2ExecuteScriptCompletedHandler;
struct ICoreWebView2GetCookiesCompletedHandler;
struct ICoreWebView2NavigationStartingEventHandler;
struct ICoreWebView2NavigationCompletedEventHandler;
struct ICoreWebView2NewWindowRequestedEventHandler;

static const IID IID_ICoreWebView2 = {0x76eceacb,0x0462,0x4d94,{0xac,0x83,0x42,0x3a,0x67,0x93,0x77,0x5e}};
static const IID IID_ICoreWebView2_2 = {0x9E8F0CF8,0xE670,0x4B5E,{0xB2,0xBC,0x73,0xE0,0x61,0xE3,0x18,0x4C}};
static const IID IID_ICoreWebView2Controller = {0x4d00c0d1,0x9434,0x4eb6,{0x80,0x78,0x86,0x97,0xa5,0x60,0x33,0x4f}};
static const IID IID_ICoreWebView2Controller2 = {0xc979903e,0xd4ca,0x4228,{0x92,0xeb,0x47,0xee,0x3f,0xa9,0x6e,0xab}};
static const IID IID_ICoreWebView2Environment = {0xb96d755e,0x0319,0x4e92,{0xa2,0x96,0x23,0x43,0x6f,0x46,0xa1,0xfc}};
static const IID IID_ICoreWebView2Settings = {0xe562e4f0,0xd7fa,0x43ac,{0x8d,0x71,0xc0,0x51,0x50,0x49,0x9f,0x00}};
static const IID IID_ICoreWebView2Settings2 = {0xee9a0f68,0xf46c,0x4e32,{0xac,0x23,0xef,0x8c,0xac,0x22,0x4d,0x2a}};
static const IID IID_ICoreWebView2CookieManager = {0x177CD9E7,0xB6F5,0x451A,{0x94,0xA0,0x5D,0x7A,0x3A,0x4C,0x41,0x41}};
static const IID IID_ICoreWebView2Cookie = {0xAD26D6BE,0x1486,0x43E6,{0xBF,0x87,0xA2,0x03,0x40,0x06,0xCA,0x21}};
static const IID IID_ICoreWebView2CookieList = {0xF7F6F714,0x5D2A,0x43C6,{0x95,0x03,0x34,0x6E,0xCE,0x02,0xD1,0x86}};
static const IID IID_ICoreWebView2NavigationStartingEventArgs = {0x5b495469,0xe119,0x438a,{0x9b,0x18,0x76,0x04,0xf2,0x5f,0x2e,0x49}};
static const IID IID_ICoreWebView2NavigationCompletedEventArgs = {0x30d68b7d,0x20d9,0x4752,{0xa9,0xca,0xec,0x84,0x48,0xfb,0xb5,0xc1}};
static const IID IID_ICoreWebView2NewWindowRequestedEventArgs = {0x34acb11c,0xfc37,0x4418,{0x91,0x32,0xf9,0xc2,0x1d,0x1e,0xaf,0xb9}};
static const IID IID_ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler = {0x4e8a3389,0xc9d8,0x4bd2,{0xb6,0xb5,0x12,0x4f,0xee,0x6c,0xc1,0x4d}};
static const IID IID_ICoreWebView2CreateCoreWebView2ControllerCompletedHandler = {0x6c4819f3,0xc9b7,0x4260,{0x81,0x27,0xc9,0xf5,0xbd,0xe7,0xf6,0x8c}};
static const IID IID_ICoreWebView2ExecuteScriptCompletedHandler = {0x49511172,0xcc67,0x4bca,{0x99,0x23,0x13,0x71,0x12,0xf4,0xc4,0xcc}};
static const IID IID_ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler = {
    0xb99369f3, 0x9b11, 0x47b5, {0xbc, 0x1f, 0x8d, 0x58, 0xbc, 0xfa, 0xed, 0x11}};
static const IID IID_ICoreWebView2Deferral = {0xc10e7f7b, 0xb585, 0x46f0, {0xa6, 0x23, 0x8b, 0xef, 0xbf, 0x3e, 0x4e, 0xe0}};
static const IID IID_ICoreWebView2GetCookiesCompletedHandler = {0x5A4F5069,0x5C15,0x47C3,{0x86,0x46,0xF4,0xDE,0x1C,0x11,0x66,0x70}};
static const IID IID_ICoreWebView2NavigationStartingEventHandler = {0x9adbe429,0xf36d,0x432b,{0x9d,0xdc,0xf8,0x88,0x1f,0xbd,0x76,0xe3}};
static const IID IID_ICoreWebView2NavigationCompletedEventHandler = {0xd33a35bf,0x1c49,0x4f98,{0x93,0xab,0x00,0x6e,0x05,0x33,0xfe,0x1c}};
static const IID IID_ICoreWebView2NewWindowRequestedEventHandler = {0xd4c185fe,0xc81c,0x4989,{0x97,0xaf,0x2d,0x3f,0xa7,0xab,0x56,0x51}};
// IIDs from Microsoft.Web.WebView2 (via webview2-com-sys); cross-checked against known-good ICoreWebView2*.
static const IID IID_ICoreWebView2WebResourceRequestedEventHandler = {0xab00b74c,0x15f1,0x4646,{0x80,0xe8,0xe7,0x63,0x41,0xd2,0x5d,0x71}};
static const IID IID_ICoreWebView2WebResourceRequestedEventArgs = {0x453e667f,0x12c7,0x49d4,{0xbe,0x6d,0xdd,0xbe,0x79,0x56,0xf5,0x7a}};
static const IID IID_ICoreWebView2WebResourceRequest = {0x97055cd4,0x512c,0x4264,{0x8b,0x5f,0xe3,0xf4,0x46,0xce,0xa6,0xa5}};
static const IID IID_ICoreWebView2WebResourceResponse = {0xaafcc94f,0xfa27,0x48fd,{0x97,0xdf,0x83,0x0e,0xf7,0x5a,0xae,0xc9}};
static const IID IID_ICoreWebView2EnvironmentOptions = {0x2fde08a8,0x1e9a,0x4766,{0x8c,0x05,0x95,0xa9,0xce,0xb9,0xd1,0xc5}};
static const IID IID_ICoreWebView2EnvironmentOptions4 = {0xac52d13f,0x0d38,0x475a,{0x9d,0xca,0x87,0x65,0x80,0xd6,0x79,0x3e}};
static const IID IID_ICoreWebView2CustomSchemeRegistration = {0xd60ac92c,0x37a6,0x4b26,{0xa3,0x9e,0x95,0xcf,0xe5,0x90,0x47,0xbb}};

MIDL_INTERFACE("d60ac92c-37a6-4b26-a39e-95cfe59047bb")
    ICoreWebView2CustomSchemeRegistration : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE get_SchemeName(LPWSTR *value) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_TreatAsSecure(BOOL *value) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_TreatAsSecure(BOOL value) = 0;
        virtual HRESULT STDMETHODCALLTYPE GetAllowedOrigins(UINT32 *count, LPWSTR **origins) = 0;
        virtual HRESULT STDMETHODCALLTYPE SetAllowedOrigins(UINT32 count, LPCWSTR *origins) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_HasAuthorityComponent(BOOL *value) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_HasAuthorityComponent(BOOL value) = 0;
    };

MIDL_INTERFACE("2fde08a8-1e9a-4766-8c05-95a9ceb9d1c5")
    ICoreWebView2EnvironmentOptions : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE get_AdditionalBrowserArguments(LPWSTR *value) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_AdditionalBrowserArguments(LPCWSTR value) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_Language(LPWSTR *value) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_Language(LPCWSTR value) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_TargetCompatibleBrowserVersion(LPWSTR *value) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_TargetCompatibleBrowserVersion(LPCWSTR value) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_AllowSingleSignOnUsingOSPrimaryAccount(BOOL *allow) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_AllowSingleSignOnUsingOSPrimaryAccount(BOOL allow) = 0;
    };

MIDL_INTERFACE("ac52d13f-0d38-475a-9dca-876580d6793e")
    ICoreWebView2EnvironmentOptions4 : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE GetCustomSchemeRegistrations(
            UINT32 *count, ICoreWebView2CustomSchemeRegistration ***schemeRegistrations) = 0;
        virtual HRESULT STDMETHODCALLTYPE SetCustomSchemeRegistrations(
            UINT32 count, ICoreWebView2CustomSchemeRegistration **schemeRegistrations) = 0;
    };

MIDL_INTERFACE("4e8a3389-c9d8-4bd2-b6b5-124fee6cc14d")
    ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Invoke(
            HRESULT errorCode,
            ICoreWebView2Environment *createdEnvironment) = 0;

    };

MIDL_INTERFACE("6c4819f3-c9b7-4260-8127-c9f5bde7f68c")
    ICoreWebView2CreateCoreWebView2ControllerCompletedHandler : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Invoke(
            HRESULT errorCode,
            ICoreWebView2Controller *createdController) = 0;

    };

MIDL_INTERFACE("49511172-cc67-4bca-9923-137112f4c4cc")
    ICoreWebView2ExecuteScriptCompletedHandler : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Invoke(
            /* [in] */ HRESULT errorCode,
            /* [in] */ LPCWSTR resultObjectAsJson) = 0;

    };

MIDL_INTERFACE("b99369f3-9b11-47b5-bc1f-8d58bcfaed11")
    ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Invoke(
            /* [in] */ HRESULT errorCode,
            /* [in] */ LPCWSTR id) = 0;
    };

MIDL_INTERFACE("c10e7f7b-b585-46f0-a623-8befbf3e4ee0")
    ICoreWebView2Deferral : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Complete(void) = 0;
    };

MIDL_INTERFACE("5A4F5069-5C15-47C3-8646-F4DE1C116670")
    ICoreWebView2GetCookiesCompletedHandler : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Invoke(
            HRESULT result,
            ICoreWebView2CookieList *cookieList) = 0;

    };

MIDL_INTERFACE("9adbe429-f36d-432b-9ddc-f8881fbd76e3")
    ICoreWebView2NavigationStartingEventHandler : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Invoke(
            /* [in] */ ICoreWebView2 *sender,
            /* [in] */ ICoreWebView2NavigationStartingEventArgs *args) = 0;

    };

MIDL_INTERFACE("d33a35bf-1c49-4f98-93ab-006e0533fe1c")
    ICoreWebView2NavigationCompletedEventHandler : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Invoke(
            /* [in] */ ICoreWebView2 *sender,
            /* [in] */ ICoreWebView2NavigationCompletedEventArgs *args) = 0;

    };

MIDL_INTERFACE("d4c185fe-c81c-4989-97af-2d3fa7ab5651")
    ICoreWebView2NewWindowRequestedEventHandler : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Invoke(
            /* [in] */ ICoreWebView2 *sender,
            /* [in] */ ICoreWebView2NewWindowRequestedEventArgs *args) = 0;

    };

MIDL_INTERFACE("ab00b74c-15f1-4646-80e8-e76341d25d71")
    ICoreWebView2WebResourceRequestedEventHandler : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE Invoke(
            ICoreWebView2 *sender,
            ICoreWebView2WebResourceRequestedEventArgs *args) = 0;
    };

MIDL_INTERFACE("97055cd4-512c-4264-8b5f-e3f446cea6a5")
    ICoreWebView2WebResourceRequest : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE get_Uri(LPWSTR *uri) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_Uri(LPCWSTR uri) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_Method(LPWSTR *method) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_Method(LPCWSTR method) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_Content(IStream **content) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_Content(IStream *content) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_Headers(ICoreWebView2HttpRequestHeaders **headers) = 0;
    };

MIDL_INTERFACE("453e667f-12c7-49d4-be6d-ddbe7956f57a")
    ICoreWebView2WebResourceRequestedEventArgs : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE get_Request(ICoreWebView2WebResourceRequest **request) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_Response(ICoreWebView2WebResourceResponse **response) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_Response(ICoreWebView2WebResourceResponse *response) = 0;
        virtual HRESULT STDMETHODCALLTYPE GetDeferral(ICoreWebView2Deferral **deferral) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_ResourceContext(COREWEBVIEW2_WEB_RESOURCE_CONTEXT *context) = 0;
    };

MIDL_INTERFACE("aafcc94f-fa27-48fd-97df-830ef75aaec9")
    ICoreWebView2WebResourceResponse : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE get_Content(IStream **content) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_Content(IStream *content) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_Headers(ICoreWebView2HttpResponseHeaders **headers) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_StatusCode(int *statusCode) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_StatusCode(int statusCode) = 0;
        virtual HRESULT STDMETHODCALLTYPE get_ReasonPhrase(LPWSTR *reasonPhrase) = 0;
        virtual HRESULT STDMETHODCALLTYPE put_ReasonPhrase(LPCWSTR reasonPhrase) = 0;
    };

MIDL_INTERFACE("5b495469-e119-438a-9b18-7604f25f2e49")
    ICoreWebView2NavigationStartingEventArgs : public IUnknown
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Uri(
            /* [retval][out] */ LPWSTR *uri) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsUserInitiated(
            /* [retval][out] */ BOOL *isUserInitiated) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsRedirected(
            /* [retval][out] */ BOOL *isRedirected) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_RequestHeaders(
            /* [retval][out] */ ICoreWebView2HttpRequestHeaders **requestHeaders) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Cancel(
            /* [retval][out] */ BOOL *cancel) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_Cancel(
            /* [in] */ BOOL cancel) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_NavigationId(
            /* [retval][out] */ UINT64 *navigationId) = 0;

    };

MIDL_INTERFACE("30d68b7d-20d9-4752-a9ca-ec8448fbb5c1")
    ICoreWebView2NavigationCompletedEventArgs : public IUnknown
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsSuccess(
            /* [retval][out] */ BOOL *isSuccess) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_WebErrorStatus(
            /* [retval][out] */ COREWEBVIEW2_WEB_ERROR_STATUS *webErrorStatus) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_NavigationId(
            /* [retval][out] */ UINT64 *navigationId) = 0;

    };

MIDL_INTERFACE("34acb11c-fc37-4418-9132-f9c21d1eafb9")
    ICoreWebView2NewWindowRequestedEventArgs : public IUnknown
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Uri(
            /* [retval][out] */ LPWSTR *uri) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_NewWindow(
            /* [in] */ ICoreWebView2 *newWindow) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_NewWindow(
            /* [retval][out] */ ICoreWebView2 **newWindow) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_Handled(
            /* [in] */ BOOL handled) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Handled(
            /* [retval][out] */ BOOL *handled) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsUserInitiated(
            /* [retval][out] */ BOOL *isUserInitiated) = 0;

        virtual HRESULT STDMETHODCALLTYPE GetDeferral(
            /* [retval][out] */ ICoreWebView2Deferral **deferral) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_WindowFeatures(
            /* [retval][out] */ ICoreWebView2WindowFeatures **value) = 0;

    };

MIDL_INTERFACE("AD26D6BE-1486-43E6-BF87-A2034006CA21")
    ICoreWebView2Cookie : public IUnknown
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Name(
            /* [retval][out] */ LPWSTR *name) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Value(
            /* [retval][out] */ LPWSTR *value) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_Value(
            /* [in] */ LPCWSTR value) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Domain(
            /* [retval][out] */ LPWSTR *domain) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Path(
            /* [retval][out] */ LPWSTR *path) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Expires(
            /* [retval][out] */ double *expires) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_Expires(
            /* [in] */ double expires) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsHttpOnly(
            /* [retval][out] */ BOOL *isHttpOnly) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_IsHttpOnly(
            /* [in] */ BOOL isHttpOnly) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_SameSite(
            /* [retval][out] */ COREWEBVIEW2_COOKIE_SAME_SITE_KIND *sameSite) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_SameSite(
            /* [in] */ COREWEBVIEW2_COOKIE_SAME_SITE_KIND sameSite) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsSecure(
            /* [retval][out] */ BOOL *isSecure) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_IsSecure(
            /* [in] */ BOOL isSecure) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsSession(
            /* [retval][out] */ BOOL *isSession) = 0;

    };

MIDL_INTERFACE("F7F6F714-5D2A-43C6-9503-346ECE02D186")
    ICoreWebView2CookieList : public IUnknown
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Count(
            /* [retval][out] */ UINT *count) = 0;

        virtual HRESULT STDMETHODCALLTYPE GetValueAtIndex(
            /* [in] */ UINT index,
            /* [retval][out] */ ICoreWebView2Cookie **cookie) = 0;

    };

MIDL_INTERFACE("177CD9E7-B6F5-451A-94A0-5D7A3A4C4141")
    ICoreWebView2CookieManager : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE CreateCookie(
            /* [in] */ LPCWSTR name,
            /* [in] */ LPCWSTR value,
            /* [in] */ LPCWSTR domain,
            /* [in] */ LPCWSTR path,
            /* [retval][out] */ ICoreWebView2Cookie **cookie) = 0;

        virtual HRESULT STDMETHODCALLTYPE CopyCookie(
            /* [in] */ ICoreWebView2Cookie *cookieParam,
            /* [retval][out] */ ICoreWebView2Cookie **cookie) = 0;

        virtual HRESULT STDMETHODCALLTYPE GetCookies(
            /* [in] */ LPCWSTR uri,
            /* [in] */ ICoreWebView2GetCookiesCompletedHandler *handler) = 0;

        virtual HRESULT STDMETHODCALLTYPE AddOrUpdateCookie(
            /* [in] */ ICoreWebView2Cookie *cookie) = 0;

        virtual HRESULT STDMETHODCALLTYPE DeleteCookie(
            /* [in] */ ICoreWebView2Cookie *cookie) = 0;

        virtual HRESULT STDMETHODCALLTYPE DeleteCookies(
            /* [in] */ LPCWSTR name,
            /* [in] */ LPCWSTR uri) = 0;

        virtual HRESULT STDMETHODCALLTYPE DeleteCookiesWithDomainAndPath(
            /* [in] */ LPCWSTR name,
            /* [in] */ LPCWSTR domain,
            /* [in] */ LPCWSTR path) = 0;

        virtual HRESULT STDMETHODCALLTYPE DeleteAllCookies( void) = 0;

    };

MIDL_INTERFACE("e562e4f0-d7fa-43ac-8d71-c05150499f00")
    ICoreWebView2Settings : public IUnknown
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsScriptEnabled(
            /* [retval][out] */ BOOL *isScriptEnabled) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_IsScriptEnabled(
            /* [in] */ BOOL isScriptEnabled) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsWebMessageEnabled(
            /* [retval][out] */ BOOL *isWebMessageEnabled) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_IsWebMessageEnabled(
            /* [in] */ BOOL isWebMessageEnabled) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_AreDefaultScriptDialogsEnabled(
            /* [retval][out] */ BOOL *areDefaultScriptDialogsEnabled) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_AreDefaultScriptDialogsEnabled(
            /* [in] */ BOOL areDefaultScriptDialogsEnabled) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsStatusBarEnabled(
            /* [retval][out] */ BOOL *isStatusBarEnabled) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_IsStatusBarEnabled(
            /* [in] */ BOOL isStatusBarEnabled) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_AreDevToolsEnabled(
            /* [retval][out] */ BOOL *areDevToolsEnabled) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_AreDevToolsEnabled(
            /* [in] */ BOOL areDevToolsEnabled) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_AreDefaultContextMenusEnabled(
            /* [retval][out] */ BOOL *enabled) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_AreDefaultContextMenusEnabled(
            /* [in] */ BOOL enabled) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_AreHostObjectsAllowed(
            /* [retval][out] */ BOOL *allowed) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_AreHostObjectsAllowed(
            /* [in] */ BOOL allowed) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsZoomControlEnabled(
            /* [retval][out] */ BOOL *enabled) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_IsZoomControlEnabled(
            /* [in] */ BOOL enabled) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsBuiltInErrorPageEnabled(
            /* [retval][out] */ BOOL *enabled) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_IsBuiltInErrorPageEnabled(
            /* [in] */ BOOL enabled) = 0;

    };

MIDL_INTERFACE("ee9a0f68-f46c-4e32-ac23-ef8cac224d2a")
    ICoreWebView2Settings2 : public ICoreWebView2Settings
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_UserAgent(
            /* [retval][out] */ LPWSTR *userAgent) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_UserAgent(
            /* [in] */ LPCWSTR userAgent) = 0;

    };

MIDL_INTERFACE("76eceacb-0462-4d94-ac83-423a6793775e")
    ICoreWebView2 : public IUnknown
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Settings(
            /* [retval][out] */ ICoreWebView2Settings **settings) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Source(
            /* [retval][out] */ LPWSTR *uri) = 0;

        virtual HRESULT STDMETHODCALLTYPE Navigate(
            /* [in] */ LPCWSTR uri) = 0;

        virtual HRESULT STDMETHODCALLTYPE NavigateToString(
            /* [in] */ LPCWSTR htmlContent) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_NavigationStarting(
            /* [in] */ ICoreWebView2NavigationStartingEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_NavigationStarting(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_ContentLoading(
            /* [in] */ ICoreWebView2ContentLoadingEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_ContentLoading(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_SourceChanged(
            /* [in] */ ICoreWebView2SourceChangedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_SourceChanged(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_HistoryChanged(
            /* [in] */ ICoreWebView2HistoryChangedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_HistoryChanged(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_NavigationCompleted(
            /* [in] */ ICoreWebView2NavigationCompletedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_NavigationCompleted(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_FrameNavigationStarting(
            /* [in] */ ICoreWebView2NavigationStartingEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_FrameNavigationStarting(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_FrameNavigationCompleted(
            /* [in] */ ICoreWebView2NavigationCompletedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_FrameNavigationCompleted(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_ScriptDialogOpening(
            /* [in] */ ICoreWebView2ScriptDialogOpeningEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_ScriptDialogOpening(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_PermissionRequested(
            /* [in] */ ICoreWebView2PermissionRequestedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_PermissionRequested(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_ProcessFailed(
            /* [in] */ ICoreWebView2ProcessFailedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_ProcessFailed(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE AddScriptToExecuteOnDocumentCreated(
            /* [in] */ LPCWSTR javaScript,
            /* [in] */ ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler *handler) = 0;

        virtual HRESULT STDMETHODCALLTYPE RemoveScriptToExecuteOnDocumentCreated(
            /* [in] */ LPCWSTR id) = 0;

        virtual HRESULT STDMETHODCALLTYPE ExecuteScript(
            /* [in] */ LPCWSTR javaScript,
            /* [in] */ ICoreWebView2ExecuteScriptCompletedHandler *handler) = 0;

        virtual HRESULT STDMETHODCALLTYPE CapturePreview(
            /* [in] */ COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT imageFormat,
            /* [in] */ IStream *imageStream,
            /* [in] */ ICoreWebView2CapturePreviewCompletedHandler *handler) = 0;

        virtual HRESULT STDMETHODCALLTYPE Reload( void) = 0;

        virtual HRESULT STDMETHODCALLTYPE PostWebMessageAsJson(
            /* [in] */ LPCWSTR webMessageAsJson) = 0;

        virtual HRESULT STDMETHODCALLTYPE PostWebMessageAsString(
            /* [in] */ LPCWSTR webMessageAsString) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_WebMessageReceived(
            /* [in] */ ICoreWebView2WebMessageReceivedEventHandler *handler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_WebMessageReceived(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE CallDevToolsProtocolMethod(
            /* [in] */ LPCWSTR methodName,
            /* [in] */ LPCWSTR parametersAsJson,
            /* [in] */ ICoreWebView2CallDevToolsProtocolMethodCompletedHandler *handler) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_BrowserProcessId(
            /* [retval][out] */ UINT32 *value) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_CanGoBack(
            /* [retval][out] */ BOOL *canGoBack) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_CanGoForward(
            /* [retval][out] */ BOOL *canGoForward) = 0;

        virtual HRESULT STDMETHODCALLTYPE GoBack( void) = 0;

        virtual HRESULT STDMETHODCALLTYPE GoForward( void) = 0;

        virtual HRESULT STDMETHODCALLTYPE GetDevToolsProtocolEventReceiver(
            /* [in] */ LPCWSTR eventName,
            /* [retval][out] */ ICoreWebView2DevToolsProtocolEventReceiver **receiver) = 0;

        virtual HRESULT STDMETHODCALLTYPE Stop( void) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_NewWindowRequested(
            /* [in] */ ICoreWebView2NewWindowRequestedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_NewWindowRequested(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_DocumentTitleChanged(
            /* [in] */ ICoreWebView2DocumentTitleChangedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_DocumentTitleChanged(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_DocumentTitle(
            /* [retval][out] */ LPWSTR *title) = 0;

        virtual HRESULT STDMETHODCALLTYPE AddHostObjectToScript(
            /* [in] */ LPCWSTR name,
            /* [in] */ VARIANT *object) = 0;

        virtual HRESULT STDMETHODCALLTYPE RemoveHostObjectFromScript(
            /* [in] */ LPCWSTR name) = 0;

        virtual HRESULT STDMETHODCALLTYPE OpenDevToolsWindow( void) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_ContainsFullScreenElementChanged(
            /* [in] */ ICoreWebView2ContainsFullScreenElementChangedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_ContainsFullScreenElementChanged(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_ContainsFullScreenElement(
            /* [retval][out] */ BOOL *containsFullScreenElement) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_WebResourceRequested(
            /* [in] */ ICoreWebView2WebResourceRequestedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_WebResourceRequested(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE AddWebResourceRequestedFilter(
            /* [in] */ const LPCWSTR uri,
            /* [in] */ const COREWEBVIEW2_WEB_RESOURCE_CONTEXT resourceContext) = 0;

        virtual HRESULT STDMETHODCALLTYPE RemoveWebResourceRequestedFilter(
            /* [in] */ const LPCWSTR uri,
            /* [in] */ const COREWEBVIEW2_WEB_RESOURCE_CONTEXT resourceContext) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_WindowCloseRequested(
            /* [in] */ ICoreWebView2WindowCloseRequestedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_WindowCloseRequested(
            /* [in] */ EventRegistrationToken token) = 0;

    };

MIDL_INTERFACE("9E8F0CF8-E670-4B5E-B2BC-73E061E3184C")
    ICoreWebView2_2 : public ICoreWebView2
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE add_WebResourceResponseReceived(
            /* [in] */ ICoreWebView2WebResourceResponseReceivedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_WebResourceResponseReceived(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE NavigateWithWebResourceRequest(
            /* [in] */ ICoreWebView2WebResourceRequest *request) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_DOMContentLoaded(
            /* [in] */ ICoreWebView2DOMContentLoadedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_DOMContentLoaded(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_CookieManager(
            /* [retval][out] */ ICoreWebView2CookieManager **cookieManager) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Environment(
            /* [retval][out] */ ICoreWebView2Environment **environment) = 0;

    };

MIDL_INTERFACE("4d00c0d1-9434-4eb6-8078-8697a560334f")
    ICoreWebView2Controller : public IUnknown
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_IsVisible(
            /* [retval][out] */ BOOL *isVisible) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_IsVisible(
            /* [in] */ BOOL isVisible) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_Bounds(
            /* [retval][out] */ RECT *bounds) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_Bounds(
            /* [in] */ RECT bounds) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_ZoomFactor(
            /* [retval][out] */ double *zoomFactor) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_ZoomFactor(
            /* [in] */ double zoomFactor) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_ZoomFactorChanged(
            /* [in] */ ICoreWebView2ZoomFactorChangedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_ZoomFactorChanged(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE SetBoundsAndZoomFactor(
            /* [in] */ RECT bounds,
            /* [in] */ double zoomFactor) = 0;

        virtual HRESULT STDMETHODCALLTYPE MoveFocus(
            /* [in] */ COREWEBVIEW2_MOVE_FOCUS_REASON reason) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_MoveFocusRequested(
            /* [in] */ ICoreWebView2MoveFocusRequestedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_MoveFocusRequested(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_GotFocus(
            /* [in] */ ICoreWebView2FocusChangedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_GotFocus(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_LostFocus(
            /* [in] */ ICoreWebView2FocusChangedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_LostFocus(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_AcceleratorKeyPressed(
            /* [in] */ ICoreWebView2AcceleratorKeyPressedEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_AcceleratorKeyPressed(
            /* [in] */ EventRegistrationToken token) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_ParentWindow(
            /* [retval][out] */ HWND *parentWindow) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_ParentWindow(
            /* [in] */ HWND parentWindow) = 0;

        virtual HRESULT STDMETHODCALLTYPE NotifyParentWindowPositionChanged( void) = 0;

        virtual HRESULT STDMETHODCALLTYPE Close( void) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_CoreWebView2(
            /* [retval][out] */ ICoreWebView2 **coreWebView2) = 0;

    };

MIDL_INTERFACE("c979903e-d4ca-4228-92eb-47ee3fa96eab")
    ICoreWebView2Controller2 : public ICoreWebView2Controller
    {
    public:
        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_DefaultBackgroundColor(
            /* [retval][out] */ COREWEBVIEW2_COLOR *backgroundColor) = 0;

        virtual /* [propput] */ HRESULT STDMETHODCALLTYPE put_DefaultBackgroundColor(
            /* [in] */ COREWEBVIEW2_COLOR backgroundColor) = 0;

    };

MIDL_INTERFACE("b96d755e-0319-4e92-a296-23436f46a1fc")
    ICoreWebView2Environment : public IUnknown
    {
    public:
        virtual HRESULT STDMETHODCALLTYPE CreateCoreWebView2Controller(
            HWND parentWindow,
            ICoreWebView2CreateCoreWebView2ControllerCompletedHandler *handler) = 0;

        virtual HRESULT STDMETHODCALLTYPE CreateWebResourceResponse(
            /* [in] */ IStream *content,
            /* [in] */ int statusCode,
            /* [in] */ LPCWSTR reasonPhrase,
            /* [in] */ LPCWSTR headers,
            /* [retval][out] */ ICoreWebView2WebResourceResponse **response) = 0;

        virtual /* [propget] */ HRESULT STDMETHODCALLTYPE get_BrowserVersionString(
            /* [retval][out] */ LPWSTR *versionInfo) = 0;

        virtual HRESULT STDMETHODCALLTYPE add_NewBrowserVersionAvailable(
            /* [in] */ ICoreWebView2NewBrowserVersionAvailableEventHandler *eventHandler,
            /* [out] */ EventRegistrationToken *token) = 0;

        virtual HRESULT STDMETHODCALLTYPE remove_NewBrowserVersionAvailable(
            /* [in] */ EventRegistrationToken token) = 0;

    };

typedef HRESULT (STDMETHODCALLTYPE *FnCreateCoreWebView2EnvironmentWithOptions)(
    PCWSTR browserExecutableFolder, PCWSTR userDataFolder,
    ICoreWebView2EnvironmentOptions *environmentOptions,
    ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler *handler);

inline FnCreateCoreWebView2EnvironmentWithOptions
xu_try_webview2_create_env(const wchar_t *path, HMODULE *out_mod) {
  if (!path || !path[0]) return NULL;
  HMODULE m = LoadLibraryW(path);
  if (!m) return NULL;
  auto fn = (FnCreateCoreWebView2EnvironmentWithOptions)GetProcAddress(
      m, "CreateCoreWebView2EnvironmentWithOptions");
  if (fn) {
    if (out_mod) *out_mod = m;
    return fn;
  }
  FreeLibrary(m);
  return NULL;
}

// Resolve CreateCoreWebView2EnvironmentWithOptions.
// Prefer WebView2Loader.dll under XU_UI_TMP (pack always extracts there), then
// next to this .exe, then PATH.
// Note: WebView2 *engine* stays the system Evergreen Runtime; only this small bootstrap
// DLL is loadable. Microsoft's WebView2LoaderStatic.lib is MSVC-only (~10MB) and not
// linked from MinGW packs — oneexe embeds the DLL bytes and extracts at startup.
inline FnCreateCoreWebView2EnvironmentWithOptions
xu_load_webview2_create_env(HMODULE *out_mod) {
  if (out_mod) *out_mod = NULL;
  FnCreateCoreWebView2EnvironmentWithOptions fn = NULL;
  wchar_t wpath[MAX_PATH];

  wchar_t tmpw[MAX_PATH];
  DWORD n = GetEnvironmentVariableW(L"XU_UI_TMP", tmpw, MAX_PATH);
  if (n > 0 && n < MAX_PATH) {
    size_t len = wcslen(tmpw);
    if (len + 22 < MAX_PATH) {
      wcscpy(wpath, tmpw);
      if (len > 0 && wpath[len - 1] != L'\\' && wpath[len - 1] != L'/') {
        wpath[len++] = L'\\';
        wpath[len] = 0;
      }
      wcscpy(wpath + len, L"WebView2Loader.dll");
      fn = xu_try_webview2_create_env(wpath, out_mod);
      if (fn) return fn;
    }
  }

  if (GetModuleFileNameW(NULL, wpath, MAX_PATH) > 0) {
    wchar_t *slash = wcsrchr(wpath, L'\\');
    if (slash) {
      wcscpy(slash + 1, L"WebView2Loader.dll");
      fn = xu_try_webview2_create_env(wpath, out_mod);
      if (fn) return fn;
    }
  }

  const wchar_t *names[] = { L"WebView2Loader.dll", L"WebView2Loader_x64.dll", NULL };
  for (int i = 0; names[i]; i++) {
    fn = xu_try_webview2_create_env(names[i], out_mod);
    if (fn) return fn;
  }
  return NULL;
}

#endif // __cplusplus
#endif // WEBVIEW2_MIN_H
