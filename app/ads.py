import logging
from kivy.utils import platform

logger = logging.getLogger(__name__)

AD_UNIT_STARTUP = "test-interstitial-startup"
AD_UNIT_SCAN = "test-interstitial-scan"

_initialized = False
_activity = None
_context = None
_refs = []
_sdk_available = False


def _check_sdk():
    global _activity, _context, _sdk_available
    if not platform == 'android':
        return False
    try:
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        _activity = PythonActivity.mActivity
        _context = _activity.getApplicationContext()
        autoclass('ru.rustore.sdk.ads.RuStoreAds')
        autoclass('ru.rustore.sdk.ads.interstitial.InterstitialAd')
        autoclass('ru.rustore.sdk.ads.AdsInitListener')
        autoclass('ru.rustore.sdk.ads.interstitial.InterstitialLoadCallback')
        autoclass('ru.rustore.sdk.ads.interstitial.InterstitialShowCallback')
        _sdk_available = True
        return True
    except Exception as e:
        logger.warning(f"RuStore Ads SDK не доступен: {e}")
        return False


def init_ads():
    global _initialized, _refs
    if not _check_sdk():
        return

    try:
        from jnius import autoclass, PythonJavaClass, java_method
        RuStoreAds = autoclass('ru.rustore.sdk.ads.RuStoreAds')

        class AdsInitCallback(PythonJavaClass):
            __javainterfaces__ = ['ru.rustore.sdk.ads.AdsInitListener']

            @java_method('()V', name='onInitSuccess')
            def onInitSuccess(self):
                global _initialized
                _initialized = True
                logger.info("RuStore Ads SDK инициализирован")

            @java_method('(Lru/rustore/sdk/core/model/AdsError;)V', name='onInitError')
            def onInitError(self, error):
                logger.error(f"RuStore Ads ошибка инициализации: {error}")

        callback = AdsInitCallback()
        _refs.append(callback)
        RuStoreAds.init(_context, callback)
        logger.info("RuStore Ads: инициализация запущена")
    except Exception as e:
        logger.exception(f"RuStore Ads: ошибка при инициализации: {e}")


def show_interstitial(ad_unit_id: str):
    if not _sdk_available:
        return
    if not _initialized:
        logger.warning("RuStore Ads: SDK не готов")
        return

    try:
        from jnius import autoclass, PythonJavaClass, java_method
        InterstitialAd = autoclass('ru.rustore.sdk.ads.interstitial.InterstitialAd')

        class LoadCallback(PythonJavaClass):
            __javainterfaces__ = ['ru.rustore.sdk.ads.interstitial.InterstitialLoadCallback']

            _loaded_ad = None

            @java_method('(Lru/rustore/sdk/ads/interstitial/InterstitialAd;)V', name='onLoaded')
            def onLoaded(self, ad):
                self._loaded_ad = ad
                logger.info("RuStore Ads: межстраничная реклама загружена")

                class ShowCallback(PythonJavaClass):
                    __javainterfaces__ = ['ru.rustore.sdk.ads.interstitial.InterstitialShowCallback']

                    @java_method('()V', name='onClosed')
                    def onClosed(self):
                        logger.info("RuStore Ads: реклама закрыта")

                    @java_method('(Lru/rustore/sdk/core/model/AdsError;)V', name='onError')
                    def onError(self, error):
                        logger.error(f"RuStore Ads: ошибка показа: {error}")

                    @java_method('()V', name='onShown')
                    def onShown(self):
                        logger.info("RuStore Ads: реклама показана")

                show_cb = ShowCallback()
                _refs.append(show_cb)
                ad.show(_activity, show_cb)

            @java_method('(Lru/rustore/sdk/core/model/AdsError;)V', name='onError')
            def onError(self, error):
                logger.error(f"RuStore Ads: ошибка загрузки рекламы: {error}")

        load_cb = LoadCallback()
        _refs.append(load_cb)
        InterstitialAd.load(_context, ad_unit_id, load_cb)
        logger.info(f"RuStore Ads: загрузка межстраничной рекламы")
    except Exception as e:
        logger.exception(f"RuStore Ads: ошибка показа: {e}")
