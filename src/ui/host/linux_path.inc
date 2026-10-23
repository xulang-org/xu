// Prepared geometry is immutable. Store Cairo's public double path data
// directly: using a temporary Cairo context would quantize large coordinates
// before the canvas CTM has a chance to translate them into view.
struct DrawPath {
  unsigned flags;
  double width,miter;
  std::vector<cairo_path_data_t> data;
  cairo_path_t native={};
  void header(cairo_path_data_type_t type,int length) { cairo_path_data_t v={};v.header.type=type;v.header.length=length;data.push_back(v); }
  void point(double x,double y) { cairo_path_data_t v={};v.point.x=x;v.point.y=y;data.push_back(v); }
  explicit DrawPath(const unsigned char *p) : flags(xdf_u32(p)),width(xdf_f64(p+16)),miter(xdf_f64(p+24)) {
    unsigned count=xdf_u32(p+8),cursor=48; double x=0,y=0; bool drawn=false;
    for(unsigned i=0;i<count;++i) {
      unsigned verb=xdf_u32(p+cursor),n=xup_values(verb);cursor+=4;
      double v[6]={};for(unsigned j=0;j<n;++j)v[j]=xdf_f64(p+cursor+j*8);cursor+=n*8;
      if(verb==XUP_MOVE) {header(CAIRO_PATH_MOVE_TO,2);point(v[0],v[1]);x=v[0];y=v[1];drawn=false;}
      else if(verb==XUP_LINE) {
        if(x!=v[0] || y!=v[1]) {header(CAIRO_PATH_LINE_TO,2);point(v[0],v[1]);drawn=true;}x=v[0];y=v[1];
      } else if(verb==XUP_CLOSE) {if(drawn)header(CAIRO_PATH_CLOSE_PATH,1);}
      else {
        if(verb==XUP_QUAD) {
          double ex=v[2],ey=v[3];v[4]=ex;v[5]=ey;
          v[2]=ex+(v[0]-ex)*2/3;v[3]=ey+(v[1]-ey)*2/3;v[0]=x+(v[0]-x)*2/3;v[1]=y+(v[1]-y)*2/3;
        }
        if(x!=v[0] || y!=v[1] || x!=v[2] || y!=v[3] || x!=v[4] || y!=v[5]) {
          header(CAIRO_PATH_CURVE_TO,4);for(unsigned j=0;j<3;++j)point(v[j*2],v[j*2+1]);drawn=true;
        }
        x=v[4];y=v[5];
      }
    }
    native.status=CAIRO_STATUS_SUCCESS;native.num_data=(int)data.size();native.data=data.data();
  }
};
