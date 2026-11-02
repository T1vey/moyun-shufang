#include "ik_target.h"
#include <cstdio>
#include <cmath>

int main() {
    FILE *f=std::fopen("target_vectors.txt","r");
    if(!f) {std::puts("Missing target_vectors.txt");return 1;}
    int count=0,failed=0; if(std::fscanf(f,"%d",&count)!=1||count<1) return 1;
    for(int row=0;row<count;++row) {
        float v[44],golden[5];int arg[5];
        for(int i=0;i<44;++i) if(std::fscanf(f,"%f",v+i)!=1) return 1;
        for(int i=0;i<5;++i) if(std::fscanf(f,"%d",arg+i)!=1) return 1;
        for(int i=0;i<5;++i) if(std::fscanf(f,"%f",golden+i)!=1) return 1;
        float q[5],pe=0,te=0;int used=0,evals=0;unsigned int magic=0;
        int status=z20_ik_target(v,v+5,v+8,v+11,v+17,v+23,v+26,v+29,
            v[39],v[40],v[41],v[42],v[43],arg[0],arg[1],arg[2],arg[3],
            q,&pe,&te,&used,&evals,&magic);
        bool bad=magic!=0x534f0301u||used<0||used>arg[0]||evals<0||evals>1+arg[0]*arg[1];
        bad=bad||(arg[4]<0?status==0:status!=arg[4]);
        if(status==0) {
            bad=bad||!std::isfinite(pe)||!std::isfinite(te)||pe>v[41]||te>v[42];
            for(int i=0;i<5;++i) bad=bad||!std::isfinite(q[i])||q[i]<v[29+2*i]||q[i]>v[30+2*i]||std::fabs(q[i]-golden[i])>.003f;
        }
        if(bad) {++failed;std::printf("FAIL row=%d status=%d wanted=%d used=%d pe=%g te=%g\n",row,status,arg[4],used,pe,te);}
    }
    std::fclose(f);std::printf("TARGET_VECTOR_GATE cases=%d failed=%d\n",count,failed);
    return failed?1:0;
}
