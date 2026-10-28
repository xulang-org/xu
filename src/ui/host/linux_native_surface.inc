// This plane only targets its children. Empty regions pass through to Canvas.
typedef struct {GtkFixed parent;} XuNativePlane;
typedef struct {GtkFixedClass parent;} XuNativePlaneClass;
G_DEFINE_TYPE(XuNativePlane,xu_native_plane,GTK_TYPE_FIXED)
static gboolean xu_native_plane_contains(GtkWidget *,double,double) {return FALSE;}
static void xu_native_plane_class_init(XuNativePlaneClass *klass) {GTK_WIDGET_CLASS(klass)->contains=xu_native_plane_contains;}
static void xu_native_plane_init(XuNativePlane *) {}
// GtkOverlay supplies a native plane above the draw widget. A custom clip
// container preserves the full DOM viewport when only part is visible.
typedef struct {GtkWidget parent;GtkWidget *child;double dx,dy,width,height,radius;} XuNativeClip;
typedef struct {GtkWidgetClass parent;} XuNativeClipClass;
G_DEFINE_TYPE(XuNativeClip,xu_native_clip,GTK_TYPE_WIDGET)
static void xu_native_clip_measure(GtkWidget *,GtkOrientation,int,int *minimum,int *natural,int *minimum_baseline,int *natural_baseline) {
  *minimum=*natural=0;if(minimum_baseline)*minimum_baseline=-1;if(natural_baseline)*natural_baseline=-1;
}
static void xu_native_clip_allocate(GtkWidget *widget,int,int,int) {
  auto *clip=(XuNativeClip *)widget;if(!clip->child)return;graphene_point_t point={(float)clip->dx,(float)clip->dy};
  gtk_widget_allocate(clip->child,(int)ceil(clip->width),(int)ceil(clip->height),-1,gsk_transform_translate(NULL,&point));
}
static void xu_native_clip_snapshot(GtkWidget *widget,GtkSnapshot *snapshot) {
  auto *clip=(XuNativeClip *)widget;if(!clip->child)return;
  graphene_rect_t visible=GRAPHENE_RECT_INIT(0,0,(float)gtk_widget_get_width(widget),(float)gtk_widget_get_height(widget));
  graphene_rect_t full=GRAPHENE_RECT_INIT((float)clip->dx,(float)clip->dy,(float)clip->width,(float)clip->height);GskRoundedRect rounded;
  gsk_rounded_rect_init_from_rect(&rounded,&full,(float)clip->radius);
  gtk_snapshot_push_clip(snapshot,&visible);gtk_snapshot_push_rounded_clip(snapshot,&rounded);
  gtk_widget_snapshot_child(widget,clip->child,snapshot);gtk_snapshot_pop(snapshot);gtk_snapshot_pop(snapshot);
}
static void xu_native_clip_dispose(GObject *object) {
  auto *clip=(XuNativeClip *)object;if(clip->child){gtk_widget_unparent(clip->child);clip->child=NULL;}
  G_OBJECT_CLASS(xu_native_clip_parent_class)->dispose(object);
}
static void xu_native_clip_class_init(XuNativeClipClass *klass) {
  auto *widget=GTK_WIDGET_CLASS(klass);widget->measure=xu_native_clip_measure;widget->size_allocate=xu_native_clip_allocate;widget->snapshot=xu_native_clip_snapshot;
  G_OBJECT_CLASS(klass)->dispose=xu_native_clip_dispose;
}
static void xu_native_clip_init(XuNativeClip *clip) {gtk_widget_set_overflow(GTK_WIDGET(clip),GTK_OVERFLOW_HIDDEN);}
