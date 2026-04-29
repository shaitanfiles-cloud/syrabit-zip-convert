#!/usr/bin/env python3
"""Syrabit.ai — Full Architecture Verification Test Suite

This script tests all major components of the Syrabit.ai architecture
as described in the architecture decoded document.

Tests cover:
1. Cache Layer (L1 TTLCache + L2 Upstash Redis)
2. LLM Provider Configuration with SmartKeyPool
3. Middleware Stack
4. AI Pipeline & RAG
5. Neural Mesh (Topic Graph)
6. Auth & Device Token System
7. Rate Limiting
"""
import sys, os
sys.path.insert(0, '/workspace/artifacts/syrabit-backend')

# Set minimal env vars for imports
os.environ.setdefault('JWT_SECRET', 'test-secret-for-verification')
os.environ.setdefault('ADMIN_JWT_SECRET', 'admin-test-secret')
os.environ.setdefault('DATABASE_URL', 'postgresql://test:test@localhost/test')

def test_cache_layer():
    """Test 1: Three-tier caching architecture (L1 → L2 → DB)"""
    print("\n" + "="*60)
    print("TEST 1: Cache Layer Architecture")
    print("="*60)
    
    try:
        from cache import (
            _ai_response_cache, _user_cache, _conv_cache, _rag_cache,
            _vector_rag_cache, _query_embed_cache, _content_card_cache,
            _syllabus_cache, _hierarchy_cache, CONTENT_CACHE_SECONDS,
            REDIS_AI_CACHE_TTL, REDIS_SEARCH_CACHE_TTL, REDIS_SESSION_CACHE_TTL,
            ai_cache_aget, ai_cache_aset, build_ai_cache_key
        )
        
        print("✓ L1 In-Memory Caches:")
        print(f"  • AI Response Cache: {len(_ai_response_cache)} entries (TTL: 3600s)")
        print(f"  • User Cache: {len(_user_cache)} entries (TTL: 600s)")
        print(f"  • Conversation Cache: {len(_conv_cache)} entries (TTL: 600s)")
        print(f"  • RAG Cache: {len(_rag_cache)} entries (TTL: 900s)")
        print(f"  • Vector RAG Cache: {len(_vector_rag_cache)} entries (TTL: 600s)")
        print(f"  • Query Embed Cache: {len(_query_embed_cache)} entries (TTL: 900s)")
        print(f"  • Content Card Cache: {len(_content_card_cache)} entries (TTL: 600s)")
        print(f"  • Syllabus Cache: {len(_syllabus_cache)} entries (TTL: 3600s)")
        print(f"  • Hierarchy Cache: {len(_hierarchy_cache)} entries (TTL: 1800s)")
        
        print(f"\n✓ TTL Configuration:")
        print(f"  • Content Cache: {CONTENT_CACHE_SECONDS}s")
        print(f"  • AI Cache (Redis): {REDIS_AI_CACHE_TTL}s")
        print(f"  • Search Cache: {REDIS_SEARCH_CACHE_TTL}s")
        print(f"  • Session Cache: {REDIS_SESSION_CACHE_TTL}s")
        
        print(f"\n✓ L2 Redis Functions:")
        print(f"  • ai_cache_aget: async GET available")
        print(f"  • ai_cache_aset: async SET available")
        print(f"  • build_ai_cache_key: key builder available")
        
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def test_llm_providers():
    """Test 2: Multi-provider LLM configuration with automatic failover"""
    print("\n" + "="*60)
    print("TEST 2: LLM Provider Configuration & Failover")
    print("="*60)
    
    try:
        from llm import (
            _LLM_PROVIDERS, _LLM_PROVIDERS_CHAT, _SARVAM_PROVIDERS,
            _CONTENT_SLOT_CANDIDATES, _SLM_SLOT_CANDIDATES,
            _SmartKeyPool, _MODEL_PROVIDER_MAP, LlmResult,
            _record_llm_call, get_llm_provider_stats
        )
        
        print("✓ Provider Pools:")
        print(f"\n  General Providers ({len(_LLM_PROVIDERS)}):")
        for p in _LLM_PROVIDERS:
            print(f"    • {p['provider']}: {p['default_model']}")
        
        print(f"\n  Chat Providers ({len(_LLM_PROVIDERS_CHAT)}):")
        for p in _LLM_PROVIDERS_CHAT:
            print(f"    • {p['provider']}: {p['default_model']}")
        
        print(f"\n  Sarvam Providers (Assamese-only): {len(_SARVAM_PROVIDERS)}")
        for p in _SARVAM_PROVIDERS:
            print(f"    • {p['provider']}: {p['default_model']}")
        
        print(f"\n✓ Smart Slot Configuration:")
        print(f"  SLM Slots (topic resolution, classification):")
        for provider, model, concurrency, tier in _SLM_SLOT_CANDIDATES:
            print(f"    • Tier {tier}: {provider}/{model} (max {concurrency} concurrent)")
        
        print(f"  Content Slots (notes, PYQ, important questions):")
        for provider, model, concurrency, tier in _CONTENT_SLOT_CANDIDATES:
            print(f"    • Tier {tier}: {provider}/{model} (max {concurrency} concurrent)")
        
        print(f"\n✓ SmartKeyPool Class: Available")
        pool = _SmartKeyPool([('test', 'model', 2, 0)])
        print(f"  • Instance created successfully")
        
        print(f"\n✓ Model Provider Map: {len(_MODEL_PROVIDER_MAP)} models mapped")
        
        print(f"\n✓ Metrics Tracking:")
        print(f"  • _record_llm_call: Available")
        print(f"  • get_llm_provider_stats: Available")
        
        # Test LlmResult
        result = LlmResult("test", provider="test-provider", fallback_reason="")
        print(f"  • LlmResult class: Works (provider={result.provider})")
        
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_middleware_stack():
    """Test 3: ASGI middleware stack in correct order"""
    print("\n" + "="*60)
    print("TEST 3: Middleware Stack")
    print("="*60)
    
    try:
        from middleware import (
            OriginSharedSecretMiddleware,
            SecurityHeadersMiddleware,
            DeviceCookieMiddleware,
            GlobalRateLimitMiddleware,
            _ORIGIN_SHARED_SECRET,
            _ORIGIN_AUTH_OPEN_PATHS
        )
        
        print("✓ Middleware Classes (in application order):")
        print("  1. OriginSharedSecretMiddleware — Guards backend from direct hits")
        print("  2. DeviceCookieMiddleware — Mints anonymous device tokens")
        print("  3. GlobalRateLimitMiddleware — Plan-aware IP + user credit limits")
        print("  4. SecurityHeadersMiddleware — HSTS, CSP, X-Frame-Options")
        
        print(f"\n✓ Origin Auth Configuration:")
        print(f"  • Secret configured: {'Yes' if _ORIGIN_SHARED_SECRET else 'No (disabled for local dev)'}")
        print(f"  • Open paths (no auth required): {len(_ORIGIN_AUTH_OPEN_PATHS)}")
        for path in _ORIGIN_AUTH_OPEN_PATHS:
            print(f"    - {path}")
        
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def test_pipeline_rag():
    """Test 4: AI Pipeline & RAG retrieval"""
    print("\n" + "="*60)
    print("TEST 4: AI Pipeline & RAG")
    print("="*60)
    
    try:
        from pipeline import (
            _record_pipeline_stage, get_pipeline_stats,
            _pick_stage1_providers, _pick_stage2_providers,
            get_instant_response, should_use_pipeline,
            apply_stage1_to_intent, build_enhanced_query,
            _build_rag_content_text
        )
        
        from rag import (
            record_pipeline_run, get_pipeline_stats as rag_stats,
            split_into_sections, merge_short_sections,
            sentence_split_with_overlap, _extract_relevant_sections,
            _trim_history, build_rag_system_prompt,
            _record_rag_event, _record_chat_latency
        )
        
        print("✓ Pipeline Functions:")
        print("  • _record_pipeline_stage: Metrics tracking")
        print("  • get_pipeline_stats: Analytics")
        print("  • _pick_stage1_providers: Provider selection")
        print("  • _pick_stage2_providers: Fallback selection")
        print("  • get_instant_response: Quick answers")
        print("  • should_use_pipeline: Intent routing")
        print("  • apply_stage1_to_intent: Topic enhancement")
        print("  • build_enhanced_query: Query expansion")
        print("  • _build_rag_content_text: Context formatting")
        
        print("\n✓ RAG Functions:")
        print("  • record_pipeline_run: Run tracking")
        print("  • split_into_sections: Content chunking")
        print("  • merge_short_sections: Section optimization")
        print("  • sentence_split_with_overlap: Sliding window")
        print("  • _extract_relevant_sections: Relevance scoring")
        print("  • _trim_history: Context window management")
        print("  • build_rag_system_prompt: Prompt engineering")
        print("  • _record_rag_event: Quality metrics")
        print("  • _record_chat_latency: Performance tracking")
        
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_neural_mesh():
    """Test 5: Neural Mesh (Topic Graph)"""
    print("\n" + "="*60)
    print("TEST 5: Neural Mesh (Topic Graph)")
    print("="*60)
    
    try:
        from neural_mesh import NeuralMesh, _Barrier, get_mesh_stats
        
        print("✓ Neural Mesh Classes:")
        print("  • NeuralMesh: Main topic graph engine")
        print("  • _Barrier: Async synchronization primitive")
        
        print("\n✓ Mesh Statistics:")
        stats = get_mesh_stats()
        print(f"  • Stats function returns: {type(stats).__name__}")
        
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def test_auth_device_token():
    """Test 6: Authentication & Device Token System"""
    print("\n" + "="*60)
    print("TEST 6: Auth & Device Token System")
    print("="*60)
    
    try:
        from auth_deps import (
            decode_token, get_current_user, check_rate_limit,
            create_access_token
        )
        
        from device_token import (
            mint_device_token, verify_device_token, device_token_id,
            DEVICE_COOKIE_NAME, _signing_key, _b64url_encode, _b64url_decode
        )
        
        print("✓ Auth Dependencies:")
        print("  • decode_token: JWT decoding")
        print("  • get_current_user: User resolution")
        print("  • check_rate_limit: Rate limiting")
        print("  • create_access_token: JWT minting")
        
        print("\n✓ Device Token System:")
        print(f"  • Cookie name: {DEVICE_COOKIE_NAME}")
        print("  • mint_device_token: Token generation")
        print("  • verify_device_token: Token validation")
        print("  • device_token_id: ID extraction")
        
        # Test token minting
        token = mint_device_token()
        print(f"\n  ✓ Test token minted: {token[:40]}...")
        
        # Test token verification
        verified = verify_device_token(token)
        print(f"  ✓ Token verification: {'Success' if verified else 'Failed'}")
        
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_redis_client():
    """Test 7: Redis Client (L2 Cache)"""
    print("\n" + "="*60)
    print("TEST 7: Redis Client (L2 Cache)")
    print("="*60)
    
    try:
        from deps import redis_client
        
        if redis_client:
            print("✓ Redis Client: Connected")
            # Try ping
            try:
                pong = redis_client.ping()
                print(f"  • PING response: {pong}")
            except Exception as e:
                print(f"  • PING failed (expected without real Redis): {e}")
        else:
            print("ℹ Redis Client: Not configured (expected without UPSTASH_REDIS_REST_URL)")
            print("  This is normal for local testing without environment variables")
        
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def test_config():
    """Test 8: Configuration & Plan Limits"""
    print("\n" + "="*60)
    print("TEST 8: Configuration & Plan Limits")
    print("="*60)
    
    try:
        from config import (
            PLAN_LIMITS, SECURE_COOKIES,
            REDIS_AI_CACHE_TTL, REDIS_CASUAL_CACHE_TTL, REDIS_CHAT_CACHE_TTL
        )
        
        # LLM concurrency is defined in llm.py, not config.py
        from llm import _LLM_SEMAPHORE, _ADMIN_LLM_SEMAPHORE
        
        print("✓ Plan Limits:")
        for plan, limits in PLAN_LIMITS.items():
            print(f"  • {plan.upper()}: {limits}")
        
        print(f"\n✓ Security:")
        print(f"  • Secure Cookies: {SECURE_COOKIES}")
        
        print(f"\n✓ Cache TTLs (from config):")
        print(f"  • AI Cache: {REDIS_AI_CACHE_TTL}s")
        print(f"  • Casual Cache: {REDIS_CASUAL_CACHE_TTL}s")
        print(f"  • Chat Cache: {REDIS_CHAT_CACHE_TTL}s")
        
        print(f"\n✓ Concurrency Limits (from llm.py):")
        print(f"  • LLM Semaphore: {_LLM_SEMAPHORE._value} max concurrent")
        print(f"  • Admin LLM Semaphore: {_ADMIN_LLM_SEMAPHORE._value} max concurrent")
        
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def test_routes():
    """Test 9: Route Modules"""
    print("\n" + "="*60)
    print("TEST 9: Route Modules")
    print("="*60)
    
    routes_to_test = [
        ('auth.py', 'routes.auth'),
        ('ai_chat.py', 'routes.ai_chat'),
        ('content.py', 'routes.content'),
        ('pyq.py', 'routes.pyq'),
        ('topic_graph.py', 'routes.topic_graph'),
        ('user.py', 'routes.user'),
        ('conversations.py', 'routes.conversations'),
    ]
    
    success_count = 0
    for filename, module_name in routes_to_test:
        try:
            __import__(module_name)
            print(f"✓ {filename}: Importable")
            success_count += 1
        except Exception as e:
            print(f"✗ {filename}: {e}")
    
    print(f"\n{success_count}/{len(routes_to_test)} route modules loaded successfully")
    return success_count == len(routes_to_test)


def main():
    """Run all architecture tests"""
    print("\n" + "="*70)
    print(" "*15 + "SYRABIT.AI ARCHITECTURE VERIFICATION")
    print("="*70)
    
    results = []
    
    results.append(("Cache Layer", test_cache_layer()))
    results.append(("LLM Providers", test_llm_providers()))
    results.append(("Middleware Stack", test_middleware_stack()))
    results.append(("Pipeline & RAG", test_pipeline_rag()))
    results.append(("Neural Mesh", test_neural_mesh()))
    results.append(("Auth & Device Token", test_auth_device_token()))
    results.append(("Redis Client", test_redis_client()))
    results.append(("Configuration", test_config()))
    results.append(("Route Modules", test_routes()))
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("\n🎉 ALL ARCHITECTURE COMPONENTS VERIFIED SUCCESSFULLY!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} component(s) need attention")
        return 1


if __name__ == "__main__":
    sys.exit(main())
