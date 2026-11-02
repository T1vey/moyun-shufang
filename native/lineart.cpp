// Deterministic CPU baselines and graph hot loops. No device or robot I/O.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <limits>
#include <locale>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <tuple>
#include <utility>
#include <vector>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C"
#endif
using P=std::pair<int,int>;
using V=std::array<double,2>;
using E=std::pair<P,P>;
using Port=std::pair<int,int>;
struct Chain {std::vector<V> points;int node[2];};
static E key(P a,P b){return a<b?E(a,b):E(b,a);}
static V vec(P p){return V{{double(p.first),double(p.second)}};}
API uint32_t tcb_lineart_native_abi(){return 0x4c4e0101;}
API void tcb_lineart_native_free(void* p){std::free(p);}

API int tcb_lineart_thin(const uint8_t* src,uint8_t* dst,unsigned w,unsigned h){
    if(!src||!dst||!w||!h||w>1536||h>1536)return -1;
    try{
        size_t n=size_t(w)*h;std::vector<uint8_t> cur(src,src+n),next(n);
        bool table[2][256];
        for(int code=0;code<256;++code){
            int p[8],b=0,a=0;for(int i=0;i<8;++i){p[i]=(code>>i)&1;b+=p[i];}
            for(int i=0;i<8;++i)a+=!p[i]&&p[(i+1)%8];
            bool c=b>=2&&b<=6&&a==1;
            table[0][code]=c&&!(p[0]*p[2]*p[4])&&!(p[2]*p[4]*p[6]);
            table[1][code]=c&&!(p[0]*p[2]*p[6])&&!(p[0]*p[4]*p[6]);
        }
        const int dx[8]={0,1,1,1,0,-1,-1,-1},dy[8]={-1,-1,0,1,1,1,0,-1};
        for(unsigned iteration=0;iteration<std::max(w,h)+2;++iteration){
            bool changed=false;
            for(int phase=0;phase<2;++phase){
                next=cur;
                for(unsigned y=0;y<h;++y)for(unsigned x=0;x<w;++x){
                    if(!cur[y*w+x])continue;
                    int code=0;
                    for(int k=0;k<8;++k){int xx=int(x)+dx[k],yy=int(y)+dy[k];
                        if(xx>=0&&yy>=0&&xx<int(w)&&yy<int(h)&&cur[yy*w+xx])code|=1<<k;}
                    if(table[phase][code]){next[y*w+x]=0;changed=true;}
                }
                cur.swap(next);
            }
            if(!changed){std::memcpy(dst,cur.data(),n);return int(2*(iteration+1));}
        }
    }catch(...){return -2;}
    return -3;
}

API void* tcb_lineart_graph(const uint8_t* src,unsigned w,unsigned h){
    if(!src||!w||!h||w>1536||h>1536)return nullptr;
    try{
        std::set<P> pixels;
        for(unsigned y=0;y<h;++y)for(unsigned x=0;x<w;++x)if(src[y*w+x])pixels.emplace(x,y);
        if(pixels.size()>250000)return nullptr;
        std::map<P,std::vector<P>> adj;
        std::set<P> junctions;
        for(P p:pixels){
            auto &neighbors=adj[p];
            for(int dy=-1;dy<=1;++dy)for(int dx=-1;dx<=1;++dx){
                P q(p.first+dx,p.second+dy);
                if((!dx&&!dy)||!pixels.count(q))continue;
                if(dx&&dy&&(pixels.count(P(p.first+dx,p.second))||pixels.count(P(p.first,p.second+dy))))continue;
                neighbors.push_back(q);
            }
            std::sort(neighbors.begin(),neighbors.end());
            if(neighbors.size()>=3)junctions.insert(p);
        }
        std::vector<V> nodes;std::map<P,int> owner;
        auto remaining=junctions;
        while(!remaining.empty()){
            P seed=*remaining.begin();remaining.erase(seed);
            std::vector<P> cluster{seed},todo{seed};
            while(!todo.empty()){
                P p=todo.back();todo.pop_back();
                for(P q:adj[p])if(remaining.erase(q)){cluster.push_back(q);todo.push_back(q);}
            }
            V sum{{0,0}};int node=int(nodes.size());
            for(P p:cluster){sum[0]+=p.first;sum[1]+=p.second;owner[p]=node;}
            sum[0]/=cluster.size();sum[1]/=cluster.size();nodes.push_back(sum);
        }
        size_t junction_count=nodes.size();
        for(P p:pixels)if(adj[p].size()==1){owner[p]=int(nodes.size());nodes.push_back(vec(p));}
        std::set<E> visited;
        for(P p:junctions)for(P q:adj[p])if(junctions.count(q)&&owner[p]==owner[q])visited.insert(key(p,q));
        size_t contracted=visited.size();std::vector<Chain> edges;
        auto node_for=[&](P p){auto it=owner.find(p);return it==owner.end()?-1:it->second;};
        auto coord=[&](P p){int node=node_for(p);return node<0?vec(p):nodes[node];};
        auto trace=[&](P p,P q){
            std::vector<V> chain{coord(p)};P previous=p,current=q;visited.insert(key(p,q));
            while(true){
                chain.push_back(coord(current));
                if(owner.count(current)||current==p)break;
                bool found=false;P next;
                for(P v:adj[current])if(v!=previous&&!visited.count(key(current,v))){next=v;found=true;break;}
                if(!found)break;
                visited.insert(key(current,next));previous=current;current=next;
            }
            chain.erase(std::unique(chain.begin(),chain.end()),chain.end());
            if(chain.size()>=2)edges.push_back(Chain{chain,{node_for(p),node_for(current)}});
        };
        for(auto &item:owner)for(P q:adj[item.first])if(!visited.count(key(item.first,q)))trace(item.first,q);
        for(P p:pixels)for(P q:adj[p])if(!visited.count(key(p,q)))trace(p,q);
        size_t raw=0;for(auto &v:adj)raw+=v.second.size();raw/=2;
        if(raw!=visited.size())throw std::runtime_error("unvisited edge");
        std::map<int,std::vector<Port>> ports;
        for(size_t i=0;i<edges.size();++i)for(int end=0;end<2;++end)if(edges[i].node[end]>=0)ports[edges[i].node[end]].emplace_back(i,end);
        auto tangent=[&](Port port){
            const auto &points=edges[port.first].points;size_t n=points.size();
            V start=points[port.second?n-1:0],v{{0,0}};
            for(size_t j=0;j<n;++j){V next=points[port.second?n-1-j:j];v={{next[0]-start[0],next[1]-start[1]}};
                if(std::sqrt(v[0]*v[0]+v[1]*v[1])>=4 || j==n-1)break;}
            double norm=std::max(std::sqrt(v[0]*v[0]+v[1]*v[1]),1e-12);v[0]/=norm;v[1]/=norm;return v;
        };
        std::map<Port,Port> pairing;
        for(auto &entry:ports){auto free=entry.second;
            while(free.size()>=2){
                std::tuple<double,Port,Port> best(std::numeric_limits<double>::infinity(),Port{},Port{});
                for(size_t i=0;i<free.size();++i)for(size_t j=i+1;j<free.size();++j){
                    V a=tangent(free[i]),b=tangent(free[j]);
                    best=std::min(best,std::make_tuple(a[0]*b[0]+a[1]*b[1],free[i],free[j]));
                }
                if(std::get<0>(best)>-std::cos(80.0*3.14159265358979323846/180.0))break;
                Port a=std::get<1>(best),b=std::get<2>(best);pairing[a]=b;pairing[b]=a;
                free.erase(std::find(free.begin(),free.end(),a));free.erase(std::find(free.begin(),free.end(),b));
            }
        }
        std::vector<Port> starts;std::set<int> used;std::vector<std::vector<V>> trails;
        for(size_t i=0;i<edges.size();++i)for(int e=0;e<2;++e)if(!pairing.count(Port(i,e)))starts.emplace_back(i,e);
        for(size_t i=0;i<edges.size();++i)starts.emplace_back(i,0);
        for(Port start:starts){int i=start.first,end=start.second;if(used.count(i))continue;
            std::vector<V> trail;
            while(!used.count(i)){
                used.insert(i);const auto &points=edges[i].points;
                for(size_t k=trail.empty()?0:1;k<points.size();++k)trail.push_back(points[end?points.size()-1-k:k]);
                auto next=pairing.find(Port(i,1-end));if(next==pairing.end())break;
                i=next->second.first;end=next->second.second;
            }
            trails.push_back(trail);
        }
        if(used.size()!=edges.size())throw std::runtime_error("unvisited chain");
        std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(17)<<"{\"trails\":[";
        for(size_t i=0;i<trails.size();++i){if(i)out<<',';out<<'[';
            for(size_t j=0;j<trails[i].size();++j){if(j)out<<',';out<<'['<<trails[i][j][0]<<','<<trails[i][j][1]<<']';}out<<']';}
        out<<"],\"graph\":{\"pixel_edges\":"<<raw<<",\"visited_pixel_edges\":"<<visited.size()
           <<",\"contracted_junction_edges\":"<<contracted<<",\"raw_chains\":"<<edges.size()
           <<",\"consumed_chains\":"<<used.size()<<",\"edge_revisits\":0,\"junction_clusters\":"<<junction_count<<"}}";
        auto data=out.str();char* result=(char*)std::malloc(data.size()+1);
        if(!result)return nullptr;std::memcpy(result,data.c_str(),data.size()+1);return result;
    }catch(...){return nullptr;}
}

API double tcb_lineart_max_distance(const double* p,unsigned n,const double* chain,unsigned m,double stop){
    if(!p||!chain||m<2)return std::numeric_limits<double>::quiet_NaN();
    double worst=0;
    for(unsigned start=0;start<n;start+=128){
        for(unsigned i=start;i<std::min(start+128,n);++i){double best=std::numeric_limits<double>::infinity();
            for(unsigned j=0;j<m-1;++j){
                double vx=chain[2*j+2]-chain[2*j],vy=chain[2*j+3]-chain[2*j+1];
                double dx=p[2*i]-chain[2*j],dy=p[2*i+1]-chain[2*j+1];
                double t=std::min(1.,std::max(0.,(dx*vx+dy*vy)/std::max(vx*vx+vy*vy,1e-20)));
                double nx=dx-t*vx,ny=dy-t*vy;best=std::min(best,nx*nx+ny*ny);
            }
            worst=std::max(worst,std::sqrt(best));
        }
        if(worst>stop)break;
    }
    return worst;
}
