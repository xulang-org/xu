// Portable, premultiplied encoded-sRGB compositing. Inputs are immutable and
// snapped together; the result is another budgeted bitmap, never an in-place
// mutation. Source opacity applies before either blending or Porter-Duff.
int xu_ui_surface_composite(uint64_t id,unsigned canvas,unsigned generation,uint64_t backdrop,uint64_t source,
                            unsigned mode,unsigned opacity) {
  if(mode>7 || opacity>65535 || !image_begin_upload(id,canvas,generation))return 0;
  lock_w();auto *slot=image_slot(id);XuUiBitmap *a=NULL,*b=NULL;
  if(slot && slot->state==IMAGE_UPLOADING && image_binding_alive(*slot)) {
    a=image_snapshot(backdrop,canvas,slot->generation);b=image_snapshot(source,canvas,slot->generation);
  }
  unlock_w();
  XuUiBitmap *out=a && b && a->width==b->width && a->height==b->height ? image_allocate(id,a->width,a->height) : NULL;
  if(out) {
    double opacity_scale=opacity/65535.;
    for(unsigned i=0;i<out->bytes;i+=4) {
      double ab=a->pixels[i+3]/255.,as=b->pixels[i+3]/255.*opacity_scale;
      double alpha=as+ab*(1-as);
      if(mode==1)alpha=as;else if(mode==2)alpha=ab*as;else if(mode==3)alpha=ab*(1-as);
      else if(mode==6)alpha=fmin(1,as+ab);else if(mode==7)alpha=as*(1-ab)+ab*(1-as);
      for(unsigned c=0;c<3;++c) {
        double cb=a->pixels[i+c]/255.,cs=b->pixels[i+c]/255.*opacity_scale,value=cs+cb*(1-as);
        switch(mode) {
          case 1:value=cs;break;case 2:value=cb*as;break;case 3:value=cb*(1-as);break;
          case 4:value=cs*(1-ab)+cb*(1-as)+cs*cb;break;
          case 5:value=cs+cb-cs*cb;break;case 6:value=fmin(1,cs+cb);break;
          case 7:value=cs*(1-ab)+cb*(1-as);break;
        }
        out->pixels[i+c]=(unsigned char)floor(fmax(0,fmin(alpha,value))*255+.5);
      }
      out->pixels[i+3]=(unsigned char)floor(alpha*255+.5);
    }
  }
  xu_ui_bitmap_release(a);xu_ui_bitmap_release(b);return image_finish_upload(id,out);
}
static int composite_upload(const void *data,unsigned len) {
  if(!data || len!=48)return 0;auto *p=(const unsigned char *)data;
  if(memcmp(p,"XUC1",4) || xdf_u32(p+4)!=1)return 0;
  auto id=[&](unsigned off){return (uint64_t)xdf_u32(p+off)|((uint64_t)xdf_u32(p+off+4)<<32);};
  return xu_ui_surface_composite(id(8),xdf_u32(p+16),xdf_u32(p+20),id(24),id(32),xdf_u32(p+40),xdf_u32(p+44));
}
