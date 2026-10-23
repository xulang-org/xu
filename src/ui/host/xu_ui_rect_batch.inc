// Exact software batching for opaque, integer-aligned axis rectangles. No
// antialiasing approximation: reject the entire optimization if a visible edge
// is fractional, any paint is translucent, or the scene contains other shapes.
// Preflight writes nothing; the immutable second pass cannot partially fall back.
struct XuRectClip {int left,top,right,bottom;};
static bool rect_batch_bounds(const double *v,const XuDrawTransform &t,XuRectClip clip,XuRectClip &out) {
  if(t.b!=0 || t.c!=0)return false;
  double xa=t.a*v[0]+t.tx,xb=t.a*(v[0]+v[2])+t.tx;
  double ya=t.d*v[1]+t.ty,yb=t.d*(v[1]+v[3])+t.ty;
  double left=fmax(clip.left,fmin(xa,xb)),right=fmin(clip.right,fmax(xa,xb));
  double top=fmax(clip.top,fmin(ya,yb)),bottom=fmin(clip.bottom,fmax(ya,yb));
  if(left>=right || top>=bottom){out={0,0,0,0};return true;}
  if(left!=floor(left) || right!=floor(right) || top!=floor(top) || bottom!=floor(bottom))return false;
  out={(int)left,(int)top,(int)right,(int)bottom};return true;
}
static bool rect_batch_walk(const XuUiFrameLease *frame,XuDrawTransform base,XuRectClip clip,unsigned width,
                             unsigned char *pixels,unsigned &work,unsigned nesting,unsigned *background) {
  if(nesting>XU_UI_LIST_MAX_NESTING)return false;
  struct State {XuDrawTransform transform;XuRectClip clip;unsigned fill;};
  State state={base,clip,0xffffffff},stack[256];unsigned depth=0,cursor=32;
  while(cursor<frame->len) {
    if(!work)return false;--work;auto *raw=(const unsigned char *)frame->body+cursor;unsigned op=xdf_u16(raw);
    if(op==XDF_BACKGROUND) {
      if(background)*background=xdf_u32(raw+8);cursor+=xdf_u32(raw+4);continue;
    }
    if(op==XDF_COLOR || op==XDF_FILL){state.fill=xdf_u32(raw+8);cursor+=xdf_u32(raw+4);continue;}
    if(op==XDF_STROKE || op==XDF_WIDTH){cursor+=xdf_u32(raw+4);continue;}
    if(op==XDF_SAVE){stack[depth++]=state;cursor+=8;continue;}
    if(op==XDF_RESTORE){state=stack[--depth];cursor+=8;continue;}
    // No large/complex payload needs rescanning during this eligibility pass.
    if(op!=XDF_ORIGIN && op!=XDF_TRANSLATE && op!=XDF_SCALE && op!=XDF_ROTATE && op!=XDF_CLIP_RECT &&
       op!=XDF_RECT && op!=XDF_FILL_RECT && op!=XDF_DISPLAY_LIST)return false;
    XuDrawCommand command;if(xdf_next(frame->body,frame->len,&cursor,&command)!=1)return false;
    if(op==XDF_DISPLAY_LIST) {
      auto *child=xu_ui_frame_list(frame,command.image_id);
      if(!child || !rect_batch_walk(child->frame,state.transform,state.clip,width,pixels,work,nesting+1,NULL))return false;
    } else if(op==XDF_RECT || op==XDF_FILL_RECT || op==XDF_CLIP_RECT) {
      XuRectClip bounds;if(!rect_batch_bounds(command.values,state.transform,state.clip,bounds))return false;
      if(op==XDF_CLIP_RECT){state.clip=bounds;continue;}
      unsigned rgba=op==XDF_RECT ? state.fill : command.rgba;
      if((rgba&255)==0)continue;if((rgba&255)!=255)return false;
      if(pixels && bounds.left<bounds.right && bounds.top<bounds.bottom) {
        unsigned char color[4]={(unsigned char)(rgba>>8),(unsigned char)(rgba>>16),(unsigned char)(rgba>>24),255};
        auto *row=pixels+((size_t)bounds.top*width+bounds.left)*4;unsigned bytes=(bounds.right-bounds.left)*4;
        for(unsigned i=0;i<bytes;i+=4)memcpy(row+i,color,4);
        for(int y=bounds.top+1;y<bounds.bottom;++y)memcpy(pixels+((size_t)y*width+bounds.left)*4,row,bytes);
      }
    } else if(op==XDF_ORIGIN)state.transform=base;
    else if(op==XDF_ROTATE){if(command.values[0]!=0)return false;}
    else if(!xdf_transform_apply(&state.transform,&command))return false;
  }
  return depth==0;
}
static bool draw_rect_batch(const XuUiFrameLease *frame,unsigned width,unsigned height,double logical_width,
                            double logical_height,unsigned char *pixels) {
  XuDrawTransform base={width/logical_width,0,0,height/logical_height,0,0};
  XuRectClip clip={0,0,(int)width,(int)height};unsigned work=XU_DRAW_FRAME_MAX_COMMANDS,background=0;
  if(!rect_batch_walk(frame,base,clip,width,NULL,work,0,&background))return false;
  // The background command sets a final clear color, regardless of where the
  // command occurs or the current clip/transform. Match all native decoders.
  if(background) {
    unsigned char color[4]={(unsigned char)(background>>8),(unsigned char)(background>>16),(unsigned char)(background>>24),255};
    for(unsigned x=0;x<width;++x)memcpy(pixels+x*4,color,4);
    for(unsigned y=1;y<height;++y)memcpy(pixels+(size_t)y*width*4,pixels,width*4);
  }
  work=XU_DRAW_FRAME_MAX_COMMANDS;
  return rect_batch_walk(frame,base,clip,width,pixels,work,0,NULL);
}
