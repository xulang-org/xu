// Shared dash geometry. Runs on the frame submitter, never the native event
// thread. No font/widget/OS objects and no registry lock are involved.
#include <vector>
#include <string>
#include <algorithm>
namespace xu_path {
struct Point { double x,y; };
static bool equal(Point a,Point b) { return a.x==b.x && a.y==b.y; }
struct Run { std::vector<Point> points; bool closed=false; };
struct Budget {
  unsigned &work;
  bool step() { if(!work) return false; --work; return true; }
};
static bool point(std::vector<Point> &points,Point p) {
  if(!points.empty() && equal(points.back(),p)) return true;
  if(points.size()>=131072) return false;
  points.push_back(p); return true;
}
static double distance(Point p,Point a,Point b) {
  double x=b.x-a.x,y=b.y-a.y,squared=x*x+y*y;
  double t=squared ? std::max(0.0,std::min(1.0,((p.x-a.x)*x+(p.y-a.y)*y)/squared)) : 0;
  return hypot(p.x-a.x-t*x,p.y-a.y-t*y);
}
static Point half(Point a,Point b) { return {(a.x+b.x)*.5,(a.y+b.y)*.5}; }
static bool cubic(std::vector<Point> &points,Point a,Point b,Point c,Point d,double tolerance,Budget &budget,unsigned depth=0) {
  if(!budget.step()) return false;
  // Distance to the finite chord also catches collinear overshoot/reversal.
  if(distance(b,a,d)<=tolerance && distance(c,a,d)<=tolerance) return point(points,d);
  if(depth==32) return false;
  auto ab=half(a,b),bc=half(b,c),cd=half(c,d),abc=half(ab,bc),bcd=half(bc,cd),mid=half(abc,bcd);
  return cubic(points,a,ab,abc,mid,tolerance,budget,depth+1) && cubic(points,mid,bcd,cd,d,tolerance,budget,depth+1);
}
static void word(std::string &out,unsigned value) { for(unsigned i=0;i<4;++i) out+=(char)(value>>(i*8)); }
static void scalar(std::string &out,double value) {
  uint64_t bits; memcpy(&bits,&value,8); for(unsigned i=0;i<8;++i) out+=(char)(bits>>(i*8));
}
static bool emit(std::string &out,unsigned &count,unsigned verb,Point p={0,0}) {
  if(count==XU_DRAW_PATH_MAX_SEGMENTS) return false;
  ++count; word(out,verb); if(verb!=XUP_CLOSE) { scalar(out,p.x); scalar(out,p.y); } return true;
}
static bool dash(const std::vector<Point> &points,bool closed,const double *pattern,unsigned count,double phase,
                   std::string &out,unsigned &segments,Budget &budget) {
  if(points.size()<2) return true;
  unsigned at=0; while(phase>=pattern[at]) { phase-=pattern[at]; at=(at+1)%count; }
  double remaining=pattern[at]-phase;
  std::vector<Run> runs;
  unsigned generated=0;
  auto append=[&](Point p) {
    if(runs.empty() || runs.back().points.empty()) return false;
    if(equal(runs.back().points.back(),p)) return true;
    if(++generated>XU_DRAW_PATH_MAX_SEGMENTS) return false;
    runs.back().points.push_back(p); return true;
  };
  bool running=false;
  for(unsigned edge=1;edge<points.size()+(closed?1u:0u);++edge) {
    Point start=points[edge-1],end=points[edge%points.size()]; double length=hypot(end.x-start.x,end.y-start.y);
    if(!length) continue;
    double consumed=0;
    while(consumed<length) {
      if(!budget.step()) return false;
      double amount=std::min(remaining,length-consumed),next=consumed+amount;
      bool on=(at&1)==0;
      Point a={start.x+(end.x-start.x)*(consumed/length),start.y+(end.y-start.y)*(consumed/length)};
      Point b=next>=length ? end : Point{start.x+(end.x-start.x)*(next/length),start.y+(end.y-start.y)*(next/length)};
      if(on) {
        if(!running) {
          if(++generated>XU_DRAW_PATH_MAX_SEGMENTS) return false;
          runs.push_back({{a},false}); running=true;
        }
        if(!append(b)) return false;
      }
      // Tiny roundoff remainders may not advance consumed, but do advance the
      // pattern. Every iteration consumes the shared finite work budget.
      consumed=next;
      if(amount>=remaining) { at=(at+1)%count; remaining=pattern[at]; if(at&1) running=false; }
      else remaining-=amount;
    }
  }
  // Join an on-run across a closed figure's origin instead of adding two caps
  // at its artificial dash seam. Other dash boundaries remain open figures.
  if(closed && !runs.empty() && equal(runs.front().points.front(),points.front()) && equal(runs.back().points.back(),points.front())) {
    if(runs.size()==1) { runs[0].closed=true; runs[0].points.pop_back(); }
    else {
      auto last=std::move(runs.back()); runs.pop_back();
      last.points.insert(last.points.end(),runs.front().points.begin()+1,runs.front().points.end());
      runs.front()=std::move(last);
    }
  }
  for(const auto &run:runs) {
    if(run.points.size()<2) continue;
    if(!emit(out,segments,XUP_MOVE,run.points[0])) return false;
    for(unsigned i=1;i<run.points.size();++i) if(!emit(out,segments,XUP_LINE,run.points[i])) return false;
    if(run.closed && !emit(out,segments,XUP_CLOSE)) return false;
  }
  return true;
}
static bool prepare(const void *data,unsigned len,std::string &out,unsigned &work) {
  if(!xup_validate(data,len)) return false;
  auto *p=(const unsigned char *)data; unsigned count=xdf_u32(p+8),dashes=xdf_u32(p+12);
  if(!dashes) return true; // caller borrows the original payload
  double pattern[XU_DRAW_PATH_MAX_DASHES],total=0;
  for(unsigned i=0;i<dashes;++i) total+=(pattern[i]=xdf_f64(p+48+i*8));
  double phase=fmod(xdf_f64(p+32),total); if(phase<0) phase+=total;
  double tolerance=xdf_f64(p+40); Budget budget{work};
  out.assign((const char *)p,48); memset(&out[8],0,8);
  unsigned cursor=48+dashes*8,segments=0;
  std::vector<Point> points;
  auto finish=[&](bool closed) { bool ok=dash(points,closed,pattern,dashes,phase,out,segments,budget);points.clear();return ok; };
  for(unsigned i=0;i<count;++i) {
    if(!budget.step()) return false;
    unsigned verb=xdf_u32(p+cursor),n=xup_values(verb); cursor+=4;
    Point v[3]; for(unsigned j=0;j<n/2;++j) v[j]={xdf_f64(p+cursor+j*16),xdf_f64(p+cursor+j*16+8)}; cursor+=n*8;
    if(verb==XUP_MOVE) { if(!finish(false) || !point(points,v[0])) return false; }
    else if(verb==XUP_CLOSE) { if(!finish(true)) return false; }
    else if(verb==XUP_LINE) { if(!point(points,v[0])) return false; }
    else {
      auto start=points.back();
      if(verb==XUP_QUAD) {
        Point a={start.x+(v[0].x-start.x)*2/3,start.y+(v[0].y-start.y)*2/3};
        Point b={v[1].x+(v[0].x-v[1].x)*2/3,v[1].y+(v[0].y-v[1].y)*2/3};
        if(!cubic(points,start,a,b,v[1],tolerance,budget)) return false;
      } else if(!cubic(points,start,v[0],v[1],v[2],tolerance,budget)) return false;
    }
  }
  if(!finish(false)) return false;
  for(unsigned j=0;j<4;++j) out[8+j]=(char)(segments>>(j*8));
  return xup_validate(out.data(),(unsigned)out.size());
}
} // namespace xu_path
