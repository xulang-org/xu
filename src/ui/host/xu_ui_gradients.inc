// Shared raster gradients. The cache is an ordinary immutable bitmap; drawing
// never regenerates stops or reruns this loop. Coordinates use logical units.
static int gradient_upload(const void *data,unsigned len) {
  if(!data || len<136 || len>104+32*16) return 0;
  auto *p=(const unsigned char *)data;
  if(memcmp(p,"XUG1",4) || xdf_u32(p+4)!=1 || xdf_u32(p+60)) return 0;
  uint64_t id=(uint64_t)xdf_u32(p+8)|((uint64_t)xdf_u32(p+12)<<32);
  unsigned canvas=xdf_u32(p+16),generation=xdf_u32(p+20),width=xdf_u32(p+24),height=xdf_u32(p+28),bytes=0;
  double lw=xdf_f64(p+32),lh=xdf_f64(p+40);
  unsigned kind=xdf_u32(p+48),spread=xdf_u32(p+52),count=xdf_u32(p+56);
  if(kind>1 || spread>2 || count<2 || count>32 || len!=104+count*16 ||
     !isfinite(lw) || !isfinite(lh) || lw<=0 || lh<=0 || lw>1e9 || lh>1e9 ||
     !image_size(width,height,width*4u,width*height*4u,&bytes) ||
     !xdf_inverse_bounded(width/lw,0,0,height/lh,1e9) || width/lw>1e9 || height/lh>1e9) return 0;
  double geometry[5];
  for(unsigned i=0;i<5;++i) { geometry[i]=xdf_f64(p+64+i*8); if(!isfinite(geometry[i]) || fabs(geometry[i])>1e9) return 0; }
  double x0=geometry[0],y0=geometry[1],dx=geometry[2]-x0,dy=geometry[3]-y0,radius=geometry[4],denom=dx*dx+dy*dy;
  if(kind==0 ? (denom<1e-12 || radius!=0) : (geometry[2]!=0 || geometry[3]!=0 || radius<1e-6)) return 0;
  struct Stop {double offset,components[4];}; Stop stops[32];
  for(unsigned i=0;i<count;++i) {
    auto *s=p+104+i*16; double offset=xdf_f64(s);unsigned rgba=xdf_u32(s+8),alpha=rgba&255;
    if(xdf_u32(s+12) || !isfinite(offset) || offset<0 || offset>1 || (i && offset<=stops[i-1].offset)) return 0;
    stops[i].offset=offset;
    // Interpolate premultiplied encoded sRGB components, then quantize once.
    // Transparent endpoints cannot leak their invisible RGB into the gradient.
    stops[i].components[0]=((rgba>>8)&255)*alpha/255.;
    stops[i].components[1]=((rgba>>16)&255)*alpha/255.;
    stops[i].components[2]=((rgba>>24)&255)*alpha/255.;stops[i].components[3]=alpha;
  }
  if(stops[0].offset!=0 || stops[count-1].offset!=1 || !image_begin_upload(id,canvas,generation)) return 0;
  auto *bitmap=image_allocate(id,width,height);
  if(bitmap) for(unsigned y=0;y<height;++y) for(unsigned x=0;x<width;++x) {
    double px=(x+.5)*(lw/width)-x0,py=(y+.5)*(lh/height)-y0;
    double t=kind==0 ? (px*dx+py*dy)/denom : hypot(px,py)/radius;
    if(spread==0) t=fmax(0,fmin(1,t));
    else {double period=spread==1 ? 1. : 2.;t=fmod(t,period);if(t<0)t+=period;if(t>1)t=2-t;}
    unsigned lo=0,hi=count-1;
    while(hi-lo>1) {unsigned mid=(lo+hi)/2;if(t<stops[mid].offset)hi=mid;else lo=mid;}
    double ratio=(t-stops[lo].offset)/(stops[hi].offset-stops[lo].offset);
    auto *target=bitmap->pixels+((size_t)y*width+x)*4;
    for(unsigned c=0;c<4;++c) target[c]=(unsigned char)floor(stops[lo].components[c]*(1-ratio)+stops[hi].components[c]*ratio+.5);
  }
  return image_finish_upload(id,bitmap);
}
