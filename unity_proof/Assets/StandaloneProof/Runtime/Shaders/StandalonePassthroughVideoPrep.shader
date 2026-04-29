Shader "QuestBowling/StandalonePassthroughVideoPrep"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _VideoGain ("Video Gain", Float) = 1.10
        _VideoGamma ("Video Gamma", Float) = 0.65
        _VideoSaturation ("Video Saturation", Float) = 1.0
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" }
        Cull Off
        ZWrite Off
        ZTest Always

        Pass
        {
            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float _VideoGain;
            float _VideoGamma;
            float _VideoSaturation;

            fixed4 frag(v2f_img input) : SV_Target
            {
                float4 source = tex2D(_MainTex, input.uv);
                float gamma = max(_VideoGamma, 0.01);
                float3 rgb = saturate(source.rgb * max(_VideoGain, 0.0));
                rgb = pow(rgb, float3(gamma, gamma, gamma));

                float luma = dot(rgb, float3(0.2126, 0.7152, 0.0722));
                rgb = lerp(float3(luma, luma, luma), rgb, max(_VideoSaturation, 0.0));

                return float4(saturate(rgb), 1.0);
            }
            ENDCG
        }
    }
}
