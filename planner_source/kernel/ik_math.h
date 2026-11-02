#ifndef SO101_IK_MATH_H
#define SO101_IK_MATH_H
#include <cmath>
#include <cfloat>
static bool finite_value(float x) { return x <= FLT_MAX && x >= -FLT_MAX; }

static void cross3(const float a[3], const float b[3], float out[3]) {
    out[0] = a[1]*b[2] - a[2]*b[1];
    out[1] = a[2]*b[0] - a[0]*b[2];
    out[2] = a[0]*b[1] - a[1]*b[0];
}

static float dot3(const float a[3], const float b[3]) {
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
}


static void mat3_vec(const float r[3][3], const float a[3], float out[3]) {
    for (int i=0; i<3; ++i)
        out[i] = r[i][0]*a[0] + r[i][1]*a[1] + r[i][2]*a[2];
}

static void mat3_mul(const float a[3][3], const float b[3][3], float out[3][3]) {
    for (int i=0; i<3; ++i) for (int j=0; j<3; ++j) {
        out[i][j] = 0.0f;
        for (int k=0; k<3; ++k) out[i][j] += a[i][k]*b[k][j];
    }
}

static void rotate_local(const float axis[3], float angle, float out[3][3]) {
    float c=std::cos(angle), s=std::sin(angle), t=1.0f-c;
    const float x=axis[0], y=axis[1], z=axis[2];
    out[0][0]=t*x*x+c;   out[0][1]=t*x*y-s*z; out[0][2]=t*x*z+s*y;
    out[1][0]=t*x*y+s*z; out[1][1]=t*y*y+c;   out[1][2]=t*y*z-s*x;
    out[2][0]=t*x*z-s*y; out[2][1]=t*y*z+s*x; out[2][2]=t*z*z+c;
}

// Geometry is the same nominal chain used by r1a/model.py. Keeping this in
// the kernel moves the expensive sin/cos, FK and task-Jacobian work to PL.
static const float OFF[5][3] = {
    {0.0612f,0.0f,0.0598f}, {0.02943f,0.0f,0.05504f},
    {0.02798f,0.0f,0.1127f}, {0.15504f,0.0f,0.00519f},
    {0.0593f,0.0f,0.00996f}
};
static const float AXIS[5][3] = {
    {0.0f,0.0f,1.0f}, {0.0f,1.0f,0.0f}, {0.0f,1.0f,0.0f},
    {0.0f,1.0f,0.0f}, {1.0f,0.0f,0.0f}
};
static const int AXIS_INDEX[5] = {2,1,1,1,0};

static void task_geometry(const float q[5], const float tool[3], const float tool_axis[3],
                          float tip[3], float current_axis[3],
                          float jacobian[6][5]) {
#ifdef SO101_TARGET_CORE
#pragma HLS INLINE off
#else
#pragma HLS INLINE
#endif
    float rotation[3][3]={{1,0,0},{0,1,0},{0,0,1}};
    float point[3]={0,0,0}, origins[5][3], world_axes[5][3];
#pragma HLS ARRAY_PARTITION variable=rotation complete dim=0
#pragma HLS ARRAY_PARTITION variable=point complete
#pragma HLS ARRAY_PARTITION variable=origins complete dim=0
#pragma HLS ARRAY_PARTITION variable=world_axes complete dim=0
#pragma HLS ARRAY_PARTITION variable=jacobian complete dim=0
    for (int i=0; i<5; ++i) {
        float shifted[3];
        mat3_vec(rotation, OFF[i], shifted);
        for (int k=0;k<3;++k) point[k]+=shifted[k];
        for (int k=0;k<3;++k) origins[i][k]=point[k];
        mat3_vec(rotation, AXIS[i], world_axes[i]);
#ifdef Z20_IK_GENERIC
        float local_rotation[3][3], next_rotation[3][3];
        rotate_local(AXIS[i],q[i],local_rotation);
        mat3_mul(rotation,local_rotation,next_rotation);
        for (int r=0;r<3;++r) for (int c=0;c<3;++c) rotation[r][c]=next_rotation[r][c];
#else
        // Z/Y/Y/Y/X chain: rotate two columns, 12 multiplies vs 27 per joint.
        const int a=(AXIS_INDEX[i]+1)%3, b=(AXIS_INDEX[i]+2)%3;
        float cs=std::cos(q[i]), sn=std::sin(q[i]);
        for(int row=0;row<3;++row) {
#pragma HLS UNROLL
            float x=rotation[row][a], y=rotation[row][b];
            rotation[row][a]=cs*x+sn*y;
            rotation[row][b]=-sn*x+cs*y;
        }
#endif
    }
    mat3_vec(rotation, tool_axis, current_axis);
    float tool_world[3]; mat3_vec(rotation,tool,tool_world);
    for (int k=0;k<3;++k) tip[k]=point[k]+tool_world[k];
    for (int i=0;i<5;++i) {
        float delta[3], linear[3], chord[3];
        for (int k=0;k<3;++k) delta[k]=tip[k]-origins[i][k];
        cross3(world_axes[i],delta,linear);
        cross3(world_axes[i],current_axis,chord);
        for (int k=0;k<3;++k) { jacobian[k][i]=linear[k]; jacobian[k+3][i]=chord[k]; }
    }
}

static int solve5(const float a_in[5][5], const float b[5], float result[5]) {
#ifdef SO101_TARGET_CORE
#pragma HLS INLINE off
#else
#pragma HLS INLINE
#endif
    float lower[5][5]={{0}};
#pragma HLS ARRAY_PARTITION variable=lower complete dim=0
#pragma HLS ARRAY_PARTITION variable=b complete
#pragma HLS ARRAY_PARTITION variable=result complete
    for (int i=0;i<5;++i) for (int k=0;k<=i;++k) {
        float pivot=a_in[i][k];
        for (int t=0;t<k;++t) pivot-=lower[i][t]*lower[k][t];
        if (!finite_value(pivot)) return 2;
        if (i==k) { if (pivot<=0.0f) return 2; lower[i][k]=std::sqrt(pivot); }
        else lower[i][k]=pivot/lower[k][k];
        if (!finite_value(lower[i][k])) return 2;
    }
    float y[5];
    for (int i=0;i<5;++i) {
        float v=b[i]; for (int k=0;k<i;++k) v-=lower[i][k]*y[k];
        y[i]=v/lower[i][i]; if (!finite_value(y[i])) return 2;
    }
    for (int rr=0;rr<5;++rr) {
        int i=4-rr; float v=y[i];
        for (int k=i+1;k<5;++k) v-=lower[k][i]*result[k];
        result[i]=v/lower[i][i]; if (!finite_value(result[i])) return 2;
    }
    return 0;
}


#endif
