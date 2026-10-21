struct DrawPath {
  unsigned flags;
  double width,miter;
  std::unique_ptr<GraphicsPath> native;
  bool valid=true;
  explicit DrawPath(const unsigned char *p) : flags(xdf_u32(p)),width(xdf_f64(p+16)),miter(xdf_f64(p+24)) {
    unsigned count=xdf_u32(p+8),cursor=48; double x=0,y=0; bool drawn=false;
    std::vector<PointF> points;std::vector<BYTE> types;points.reserve(count*3u);types.reserve(count*3u);
    auto point=[&](double px,double py,BYTE type) {points.emplace_back((REAL)px,(REAL)py);types.push_back(type);};
    auto start=[&] {if(!drawn)point(x,y,PathPointTypeStart);drawn=true;};
    for(unsigned i=0;i<count;++i) {
      unsigned verb=xdf_u32(p+cursor),n=xup_values(verb);cursor+=4;
      double v[6]={};for(unsigned j=0;j<n;++j)v[j]=xdf_f64(p+cursor+j*8);cursor+=n*8;
      if(verb==XUP_MOVE) {x=v[0];y=v[1];drawn=false;}
      else if(verb==XUP_LINE) {
        if(x!=v[0] || y!=v[1]) {start();point(v[0],v[1],PathPointTypeLine);}x=v[0];y=v[1];
      } else if(verb==XUP_CLOSE) {if(drawn)types.back()|=PathPointTypeCloseSubpath;}
      else {
        if(verb==XUP_QUAD) {
          double ex=v[2],ey=v[3];v[4]=ex;v[5]=ey;
          v[2]=ex+(v[0]-ex)*2/3;v[3]=ey+(v[1]-ey)*2/3;v[0]=x+(v[0]-x)*2/3;v[1]=y+(v[1]-y)*2/3;
        }
        if(x!=v[0] || y!=v[1] || x!=v[2] || y!=v[3] || x!=v[4] || y!=v[5]) {
          start();for(unsigned j=0;j<3;++j)point(v[j*2],v[j*2+1],PathPointTypeBezier);
        }
        x=v[4];y=v[5];
      }
    }
    // Construct once from contiguous point/type arrays. Repeated AddLine /
    // AddBezier calls can repeatedly grow a native buffer for large paths.
    auto fill=(flags&2) ? FillModeAlternate : FillModeWinding;
    native.reset(points.empty() ? new GraphicsPath(fill) : new GraphicsPath(points.data(),types.data(),(INT)points.size(),fill));
    if(native->GetLastStatus()!=Ok) valid=false;
  }
};
