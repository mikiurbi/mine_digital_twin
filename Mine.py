import simpy,random
from math import exp, sqrt

DEBUG = False

class Truck(object):
    """
    The class replicates the operations and maintenance process of a Truck. The following parameters must be passed to initialize the object.

    :param float alpha: Scale parameter of Weibull distribution
    :param float beta: Shape parameter of Weibull distribution
    :param float muCorrective: Mean time to repair
    :param float sigmaCorrective: Time to repair std. dev.
    :param float muPreventive: Mean maintenance time
    :param float sigmaPreventive: Maintenance time std. dev.
    :param float Cc: Cost of corrective maintenance
    :param float Cp: Cost of preventive maintenance
    :param float p: Probability threshold for preventive maintenance
    :param obj env: A :class:`simpy.Environment` object
    :param int id: Identification number
    :param list shovels: The list of shovels in the system
    :param list dumpsites: The list of dump sites in the system
    :param list workshops: The list of workshops in the system

    """

    preventiveMaintenanceRule = None

    def __init__(
        self,
        alpha,
        beta,
        muCorrective,
        sigmaCorrective,
        muPreventive,
        sigmaPreventive,
        Cc,
        Cp,
        p,
        env,
        id,
        shovels,
        dumpsites,
        workshops,
        muCapacity,
        sigmaCapacity,
        lastMaintenance=0,
        nextFault=None,
    ):
        self.id = id
        self.env = env
        self.process = env.process(self.run(shovels,dumpsites,workshops))
        self.alpha = alpha
        self.beta = beta
        self.capacity = random.normalvariate(mu=muCapacity,sigma=sigmaCapacity)
        self.muCorrective = muCorrective
        self.sigmaCorrective = sigmaCorrective
        self.muPreventive = muPreventive
        self.sigmaPreventive = sigmaPreventive
        self.Cc = Cc
        self.Cp = Cp
        self.lastMaintenance = 0
        self.p = p
        self.nextFault = nextFault
        self.coordinates = (0,0)
        self.broken = False
        self.priority = 3
        self.failure = env.process(self.fault(nextFault=nextFault))
        self.env.statistics["Truck%d" %self.id] = {
            "Failure": 0,
            "FailureHistory": list(),
            "PreventiveInterventions": 0,
            "PreventiveMaintenanceHistory": list(),
            "History": list(),
            "LastMaintenance": 0,
            "NextFault": 0,
            "Statistics": dict(
                TravelTime=0,
                TimeInQueue=0,
                TimeUnderLoading=0,
                TimeUnderUnloading=0,
                PMRepair=0,
                CMRepair=0,
                Failed=0,
            )}

    def run(self,shovels,dumpsites,workshops):
        """
        The method is a generator function which returns the event linked with the operations of a truck.
        """

        while True:
            try:
                # ASSIGN A SHOVEL
                shovel = self.assignment(shovels)
                # TRAVEL
                if DEBUG:
                    print("Truck%d      is traveling towards Shovel%d   at %.2f." %(self.id,shovel.id,self.env.now))
                self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      is traveling towards Shovel%d   at %.2f." %(self.id,shovel.id,self.env.now))
                t = self.env.now
                yield self.env.process(self.travel(shovel.coordinates))
                if DEBUG:
                    print("Truck%d      arrived at Shovel%d         at %.2f." %(self.id,shovel.id,self.env.now))
                self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      arrived at Shovel%d             at %.2f." %(self.id,shovel.id,self.env.now))
                self.env.statistics["Truck%d"%self.id]["Statistics"]["TravelTime"] += self.env.now - t
                t = self.env.now

                # LOAD
                loadingTime = shovel.servingTime()
                priority, flag = self.priority, 0
                while loadingTime:
                    with shovel.machine.request(priority=priority) as req:
                        yield req
                        if DEBUG:
                            print("Truck%d      start loading at Shovel%d    at %.2f." %(self.id,shovel.id,self.env.now))
                        self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      start loading at Shovel%d       at %.2f." %(self.id,shovel.id,self.env.now))
                        self.env.statistics["Truck%d"%self.id]["Statistics"]["TimeInQueue"] += self.env.now - t
                        t = self.env.now

                        try:
                            start = self.env.now
                            yield self.env.timeout(loadingTime)
                            if DEBUG:
                                print("Truck%d      loaded by Shovel%d        at %.2f." %(self.id,shovel.id,self.env.now))
                            self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      loaded by Shovel%d              at %.2f." %(self.id,shovel.id,self.env.now))
                            self.env.statistics["Truck%d"%self.id]["Statistics"]["TimeUnderLoading"] += self.env.now - t
                            self.env.statistics["Shovel%d"%shovel.id]["Statistics"]["WorkingTime"] += self.env.now - t
                            t = self.env.now
                            loadingTime = 0
                        except simpy.Interrupt as interruption:
                            if type(interruption.cause) is simpy.resources.resource.Preempted:
                                if DEBUG:
                                    print("Truck%d     interrupted loading at Shovel%d    at %.2f." %(self.id,shovel.id,self.env.now))
                                self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      interrupted loading at Shovel%d at %.2f." %(self.id,shovel.id,self.env.now))
                                loadingTime -= self.env.now - start
                                priority = 2
                                self.env.statistics["Truck%d"%self.id]["Statistics"]["TimeUnderLoading"] += self.env.now - t
                                self.env.statistics["Shovel%d"%shovel.id]["Statistics"]["WorkingTime"] += self.env.now - t
                                t = self.env.now

                            elif interruption.cause[0] == 2:
                                flag = 1
                                loadingTime = 0
                if flag == 1:
                    raise simpy.Interrupt(cause="Truck%d" % self.id)
                # CHECK SHOVEL FOR PREVENTIVE MAINTENANCE
                workshop = shovel.assignment(workshops)
                expTaskTime = shovel.distance(workshop.coordinates) + shovel.waitingTime()
                if Shovel.preventiveMaintenanceRule == 'condinal_probability':
                    doMaintenance = shovel.doPreventiveMaintenance(expTaskTime=expTaskTime)
                elif Shovel.preventiveMaintenanceRule == 'age_based':
                    doMaintenance = shovel.doPreventiveMaintenanceAgeBased(expTaskTime=expTaskTime)
                elif Shovel.preventiveMaintenanceRule is None:
                    raise EnvironmentError
                if doMaintenance:
                    # Interrupt failure process
                    shovel.failure.interrupt()
                    self.env.process(shovel.preventiveMaintenance(workshop))

                # ASSIGN A DUMPSITE
                dumpsite = self.assignment(dumpsites)

                # TRAVEL
                if DEBUG:
                    print("Truck%d      is traveling towards DumpSite%d at %.2f." %(self.id,dumpsite.id,self.env.now))
                self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      is traveling towards DumpSite%d at %.2f." %(self.id,dumpsite.id,self.env.now))
                yield self.env.process(self.travel(dumpsite.coordinates))
                if DEBUG:
                    print("Truck%d      arrived at DumpSite%d         at %.2f." %(self.id,dumpsite.id,self.env.now))
                self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      arrived at DumpSite%d           at %.2f." %(self.id,dumpsite.id,self.env.now))
                self.env.statistics["Truck%d"%self.id]["Statistics"]["TravelTime"] += self.env.now - t
                t = self.env.now

                # UNLOAD
                with dumpsite.machine.request() as req:
                    yield req
                    if DEBUG:
                        print("Truck%d      under unloading at DumpSite%d    at %.2f." %(self.id,dumpsite.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      under unloading at DumpSite%d   at %.2f." %(self.id,dumpsite.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["Statistics"]["TimeInQueue"] += self.env.now - t
                    t = self.env.now

                    yield self.env.process(dumpsite.unload(self,amount=self.capacity))
                    if DEBUG:
                        print("Truck%d      unloaded at DumpSite%d        at %.2f." %(self.id,dumpsite.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      unloaded at DumpSite%d          at %.2f." %(self.id,dumpsite.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["Statistics"]["TimeUnderUnloading"] += self.env.now - t
                    t = self.env.now

                # PREVENTIVE MAINTENANCE
                shovel = self.assignment(shovels)
                expTaskTime = self.estimateExpTaskTime(shovel)

                if self.preventiveMaintenanceRule == 'condinal_probability':
                    doMaintenance = self.doPreventiveMaintenance(expTaskTime=expTaskTime)
                elif self.preventiveMaintenanceRule == 'age_based':
                    doMaintenance = self.doPreventiveMaintenanceAgeBased(expTaskTime=expTaskTime)
                elif self.preventiveMaintenanceRule is None:
                    raise EnvironmentError
                if doMaintenance:
                    self.env.statistics["Truck%d" % self.id]["PreventiveInterventions"] += 1
                    self.env.statistics["Truck%d" % self.id]["PreventiveMaintenanceHistory"].append([self.env.now, self.Cp])
                    # ASSIGN A WORKSHOP
                    workshop = self.assignment(workshops)
                    # DELETE OLD FAULT EVENT
                    self.failure.interrupt(cause="PM%d" % self.id)
                    # TRAVEL
                    if DEBUG:
                        print("Truck%d      is traveling to Workshop%d     at %.2f." %(self.id,workshop.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      is traveling to Workshop%d     at %.2f." %(self.id,workshop.id,self.env.now))
                    yield self.env.process(self.travel(workshop.coordinates))

                    if DEBUG:
                        print("Truck%d      arrived at WorkShop%d         at %.2f." %(self.id,workshop.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      arrived at WorkShop%d         at %.2f." %(self.id,workshop.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["Statistics"]["TravelTime"] += self.env.now - t
                    t = self.env.now

                    # REPAIR
                    with workshop.machine.request(priority=2) as req:
                        yield req
                        if DEBUG:
                            print("Truck%d      under repair at Workshop%d    at %.2f." %(self.id,workshop.id,self.env.now))
                        self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      under repair at Workshop%d    at %.2f." %(self.id,workshop.id,self.env.now))
                        self.env.statistics["Truck%d"%self.id]["Statistics"]["TimeInQueue"] += self.env.now - t
                        t = self.env.now

                        yield self.env.process(workshop.preventiveMaintenance(self))
                        if DEBUG:
                            print("Truck%d      repaired by Workshop%d         at %.2f." %(self.id,workshop.id,self.env.now))
                        self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      repaired by Workshop%d         at %.2f." %(self.id,workshop.id,self.env.now))
                        self.env.statistics["Truck%d"%self.id]["Statistics"]["PMRepair"] += self.env.now - t
                        t = self.env.now

                    # REGENERATE THE FAULT EVENT
                    self.failure = self.env.process(self.fault())

            except simpy.Interrupt:
                if DEBUG:
                    self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      failed             at %.2f." % (self.id, self.env.now))
                self.env.statistics["Truck%d" %self.id]["Failure"] += 1
                self.env.statistics["Truck%d" %self.id]["FailureHistory"].append([self.env.now, self.Cc])
                # ASSIGN A WORKSHOP
                workshop = self.assignment(workshops)
                # TRAVEL
                if DEBUG:
                    print("Truck%d      is traveling to Workshop%d     at %.2f." %(self.id,workshop.id,self.env.now))
                self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      is traveling to Workshop%d      at %.2f." %(self.id,workshop.id,self.env.now))
                yield self.env.process(self.travel(workshop.coordinates))
                if DEBUG:
                    print("Truck%d      arrived at WorkShop%d         at %.2f." %(self.id,workshop.id,self.env.now))
                self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      arrived at WorkShop%d           at %.2f." %(self.id,workshop.id,self.env.now))
                self.env.statistics["Truck%d"%self.id]["Statistics"]["Failed"] += self.env.now - t
                t = self.env.now

                # REPAIR
                with workshop.machine.request(priority=2) as req:
                    yield req
                    if DEBUG:
                        print("Truck%d      under repair at Workshop%d    at %.2f." %(self.id,workshop.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      under repair at Workshop%d      at %.2f." %(self.id,workshop.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["Statistics"]["Failed"] += self.env.now - t
                    t = self.env.now
                    yield self.env.process(workshop.correctiveRepair(self))
                    if DEBUG:
                        print("Truck%d      repaired by Workshop%d         at %.2f." %(self.id,workshop.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["History"].append("Truck%d      repaired by Workshop%d          at %.2f." %(self.id,workshop.id,self.env.now))
                    self.env.statistics["Truck%d"%self.id]["Statistics"]["CMRepair"] += self.env.now - t
                    t = self.env.now
                # REGENERATE THE FAULT EVENT
                self.failure = self.env.process(self.fault())

    def fault(self, nextFault=None):
        """ The method generates a fault every now and then."""
        try:
            if nextFault is None:
                ttf = 60 * random.weibullvariate(alpha=self.alpha,beta=self.beta)
            else:
                ttf = nextFault - self.env.now
            self.nextFault = self.env.now + ttf
            self.env.statistics["Truck%d" %self.id]["NextFault"] = self.nextFault
            yield self.env.timeout(ttf)
            self.process.interrupt(cause=(2,"Truck%d" % self.id))
        except simpy.Interrupt:
            pass

    def travel(self,destination):
        travelTime = self.distance(destination)
        yield self.env.timeout(travelTime)
        self.coordinates = destination

    def distance(self,destination):
        return 0.5 * random.lognormvariate(
            mu=sqrt((self.coordinates[0] - destination[0])**2 + (self.coordinates[1] - destination[1])**2),
            sigma=0.1)

    def assignment(self,items):
        """
        The function returns the item :math:`i` (shovel, dumpsite, workshop) to which the Truck is assigned among a set of items :math:`I`, which is provided as a list.
        The value :math:`i` is returned by the following equation.

        .. math::

            \\arg\min_{i \\in I} = \{ \\mathbb{E} [ \\text{travel distance to $i$} ] + \\mathbb{E} [ \\text{waiting time at $i$} ] \}

        """
        x, candidate = 1e6, None
        for item in items:
            time = self.distance(item.coordinates) + item.waitingTime()
            if time < x:
                x, candidate = time, item
        if candidate is None:
            raise ValueError
        else:
            return candidate

    def estimateExpTaskTime(self,item):
        return self.distance(item.coordinates) + item.waitingTime()

    def doPreventiveMaintenance(self,expTaskTime):
        """
        The decision rule to trigger a preventive maintenance intervention is enclosed in the method. The rule used is the following.

        .. math::

            P(t < T < t + \Delta t | T > t) > \\text{threshold}

        The expected duration of the next tast :math:`\Delta t` is calculated using the following equation:

        .. math::

            \Delta t = \min_{i \in W} \{ \\mathbb{E} [ \\text{travel distance to $i$} ] + \\mathbb{E} [ \\text{waiting time at $i$} ] \}

        where :math:`W` is the set of workshops.

        """
        def weibull(x):
            return 1 - exp(-x/self.alpha)**self.beta

        pFailure = (weibull(self.env.now/60 - self.lastMaintenance/60 + expTaskTime/60) - weibull(self.env.now/60 - self.lastMaintenance/60)) / (1 - weibull(self.env.now/60 - self.lastMaintenance/60))

        if pFailure > self.p: return True
        else: return False

    def doPreventiveMaintenanceAgeBased(self, expTaskTime):
        """
        The function use the age of the truck to establish whether a truck must undergo preventive maintenance.
        """
        if self.env.now - self.lastMaintenance > self.p:
            return True
        else:
            return False

    def timeToRepairCorrective(self):
        return random.lognormvariate(mu=self.muCorrective,sigma=self.sigmaCorrective) * 60

    def timeToRepairPreventive(self):
        return random.lognormvariate(mu=self.muPreventive,sigma=self.sigmaPreventive) * 60


class Server(object):
    """
    This is the base class with the common attributes and methods of all server entities within the simulation.
    """

    def __init__(self,env,id,coordinates,mu=None,sigma=None):
        self.env = env
        self.id = id
        self.coordinates = coordinates
        self.mu = mu
        self.sigma = sigma
        self.broken = False

    def servingTime(self):
        return random.lognormvariate(mu=self.mu,sigma=self.sigma)


class Shovel(Server):
    """
    The class inherits the basic attributes from :class:`Server`. It includes the method to replicate the operations in case of preventive maintenance of a shovel.

    :param obj env: A :class:`simpy.Environment` object
    :param int id: Identification number
    :param tuple coordinates: the (*x*, *y*) coordinates of the site on the map
    :param float mu: mean of the (lognormal) serving time distribution
    :param float sigma: st. dev. of the (lognormal) serving time distribution
    :param float alpha: Scale parameter of Weibull distribution
    :param float beta: Shape parameter of Weibull distribution
    :param float muCorrective: Mean time to repair
    :param float sigmaCorrective: Time to repair std. dev.
    :param float muPreventive: Mean maintenance time
    :param float sigmaPreventive: Maintenance time std. dev.
    :param float Cc: Cost of corrective maintenance
    :param float Cp: Cost of preventive maintenance
    :param float p: Probability threshold for preventive maintenance
    :param list workshops: The list of workshops in the system

    """

    preventiveMaintenanceRule = None

    def __init__(
        self,
        env,
        id,
        coordinates,
        mu,
        sigma,
        alpha,
        beta,
        muPreventive,
        sigmaPreventive,
        muCorrective,
        sigmaCorrective,
        Cc,
        Cp,
        p,
        workshops,
        lastMaintenance=0,
        nextFault=None,
    ):
        super().__init__(env, id, coordinates,mu,sigma)
        self.alpha = alpha
        self.beta = beta
        self.muPreventive = muPreventive
        self.sigmaPreventive = sigmaPreventive
        self.muCorrective = muCorrective
        self.sigmaCorrective = sigmaCorrective
        self.machine = simpy.PreemptiveResource(env,capacity=1)
        self.nextFault = nextFault
        self.Cc = Cc
        self.Cp = Cp
        self.lastMaintenance = 0
        self.p = p
        self.workshops = workshops
        self.failure = env.process(self.fault(nextFault=nextFault))

        env.statistics["Shovel%d" %self.id] = {
            "Failure": 0,
            "FailureHistory": list(),
            "PreventiveInterventions": 0,
            "PreventiveMaintenanceHistory": list(),
            "History": list(),
            "LastMaintenance": 0,
            "NextFault": 0,
            "Statistics": dict(
                TravelTime=0,
                TimeInQueue=0,
                PMRepair=0,
                CMRepair=0,
                Failed=0,
                WorkingTime=0,
            )}

    def timeToFailure(self):
        return 60 * random.weibullvariate(alpha=self.alpha,beta=self.beta)

    def load(self):
        yield self.env.timeout(self.servingTime())

    def waitingTime(self):
        return (len(self.machine.queue) + self.machine.count) * self.mu

    def timeToRepairCorrective(self):
        return random.lognormvariate(mu=self.muCorrective,sigma=self.sigmaCorrective) * 60

    def timeToRepairPreventive(self):
        return random.lognormvariate(mu=self.muPreventive,sigma=self.sigmaPreventive) * 60

    def assignment(self,items):
        x, candidate = 1e6, None
        for item in items:
            if not item.broken:
                time = self.distance(item.coordinates) + item.waitingTime()
                if time < x:
                    x, candidate = time, item
        if candidate is None:
            raise ValueError
        else:
            return candidate

    def distance(self,destination):
        return 0.5 * random.lognormvariate(
            mu=sqrt((self.coordinates[0] - destination[0])**2 + (self.coordinates[1] - destination[1])**2),
            sigma=0.1)

    def travel(self,destination):
        travelTime = self.distance(destination)
        yield self.env.timeout(travelTime)

    def fault(self, nextFault=None):

        while True:
            try:
                if nextFault is None:
                    ttf = self.timeToFailure()
                else:
                    ttf = nextFault - self.env.now
                self.nextFault = self.env.now + ttf
                self.env.statistics["Shovel%d" %self.id]["NextFault"] = self.nextFault
                yield self.env.timeout(ttf)
                if not self.broken:
                    with self.machine.request(priority=1) as req:
                        self.broken = True
                        if DEBUG:
                            print("Shovel%d     failed                at %.2f." % (self.id, self.env.now))
                        self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     failed                         at %.2f." % (self.id, self.env.now))
                        self.env.statistics["Shovel%d" %self.id]["Failure"] += 1
                        self.env.statistics["Shovel%d" %self.id]["FailureHistory"].append([self.env.now, self.id, self.Cc])
                        yield req
                        # ASSIGN WORKSHOP
                        workshop = self.assignment(self.workshops)
                        # TRAVEL
                        if DEBUG:
                            print("Shovel%d     is traveling towards Workshop%d at %.2f." %(self.id,workshop.id,self.env.now))
                        self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     is traveling towards Workshop%d at %.2f." %(self.id,workshop.id,self.env.now))
                        t = self.env.now

                        yield self.env.process(self.travel(workshop.coordinates))
                        if DEBUG:
                            print("Shovel%d     arrived at Workshop%d        at %.2f." %(self.id,workshop.id,self.env.now))
                        self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     arrived at Workshop%d           at %.2f." %(self.id,workshop.id,self.env.now))
                        self.env.statistics["Shovel%d" %self.id]["Statistics"]["Failed"] += self.env.now - t
                        t = self.env.now

                        # REPAIR
                        with workshop.machine.request(priority=1) as req:
                            yield req
                            if DEBUG:
                                print("Shovel%d     is under repair at Workshop%d    at %.2f." %(self.id,workshop.id,self.env.now))
                            self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     is under repair at Workshop%d   at %.2f." %(self.id,workshop.id,self.env.now))
                            self.env.statistics["Shovel%d" %self.id]["Statistics"]["TimeInQueue"] += self.env.now - t
                            t = self.env.now

                            self.lastMaintenance = self.env.now
                            yield self.env.timeout(self.timeToRepairCorrective())
                            if DEBUG:
                                print("Shovel%d     repaired at Workshop%d        at %.2f." %(self.id,workshop.id,self.env.now))
                            self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     repaired at Workshop%d          at %.2f." %(self.id,workshop.id,self.env.now))
                            self.env.statistics["Shovel%d" %self.id]["Statistics"]["CMRepair"] += self.env.now - t
                            t = self.env.now

                        # TRAVEL
                        if DEBUG:
                            print("Shovel%d     is traveling towards its site    at %.2f." %(self.id,self.env.now))
                        self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     is traveling towards its site  at %.2f." %(self.id,self.env.now))
                        yield self.env.process(self.travel(workshop.coordinates))
                        if DEBUG:
                            print("Shovel%d     arrived at its site        at %.2f." %(self.id,self.env.now))
                        self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     arrived at its site            at %.2f." %(self.id,self.env.now))
                        self.env.statistics["Shovel%d" %self.id]["Statistics"]["TravelTime"] += self.env.now - t
                        self.broken = False
            except simpy.Interrupt:
                break

    def doPreventiveMaintenance(self,expTaskTime):
        """
        The decision rule to trigger a preventive maintenance intervention is enclosed in the method. The rule used is the following.

        .. math::

            P(t < T < \\Delta t | T > t) > \\text{threshold}

        """
        def weibull(x):
            return 1 - exp(-x/self.alpha)**self.beta

        pFailure = (weibull(self.env.now/60 - self.lastMaintenance/60 + expTaskTime/60) - weibull(self.env.now/60 - self.lastMaintenance/60)) / (1 - weibull(self.env.now/60 - self.lastMaintenance/60))

        if pFailure > self.p: return True
        else: return False

    def doPreventiveMaintenanceAgeBased(self, expTaskTime):
        """
        The function use the age of the truck to establish whether a truck must undergo preventive maintenance.
        """
        if self.env.now - self.lastMaintenance > self.p:
            return True
        else:
            return False

    def preventiveMaintenance(self,workshop):
        """
        The method is a generator function which replicates the maintenance operations for a shovel in case of preventive maintenance.
        """
        with self.machine.request(priority=1) as req:
            if DEBUG:
                print("Shovel%d     failed                at %.2f." % (self.id, self.env.now))
            self.env.statistics["Shovel%d" %self.id]["PreventiveInterventions"] += 1
            self.env.statistics["Shovel%d" %self.id]["PreventiveMaintenanceHistory"].append([self.env.now, self.id, self.Cp])
            yield req
            # TRAVEL
            if DEBUG:
                print("Shovel%d     is traveling towards Workshop%d    at %.2f." %(self.id,workshop.id,self.env.now))
            self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     is traveling towards Workshop%d at %.2f." %(self.id,workshop.id,self.env.now))
            yield self.env.process(self.travel(workshop.coordinates))
            t = self.env.now

            if DEBUG:
                print("Shovel%d     arrived at Workshop%d        at %.2f." %(self.id,workshop.id,self.env.now))
            self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     arrived at Workshop%d           at %.2f." %(self.id,workshop.id,self.env.now))
            self.env.statistics["Shovel%d" %self.id]["Statistics"]["TravelTime"] += self.env.now - t
            t = self.env.now

            # REPAIR
            with workshop.machine.request(priority=1) as req:
                yield req
                if DEBUG:
                    print("Shovel%d     is under repair at Workshop%d    at %.2f." %(self.id,workshop.id,self.env.now))
                self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     is under repair at Workshop%d   at %.2f." %(self.id,workshop.id,self.env.now))
                self.lastMaintenance = self.env.now
                self.env.statistics["Shovel%d" %self.id]["Statistics"]["TimeInQueue"] += self.env.now - t
                t = self.env.now

                yield self.env.timeout(self.timeToRepairCorrective())
                if DEBUG:
                    print("Shovel%d     repaired at Workshop%d        at %.2f." %(self.id,workshop.id,self.env.now))
                self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     repaired at Workshop%d          at %.2f." %(self.id,workshop.id,self.env.now))
                self.env.statistics["Shovel%d" %self.id]["Statistics"]["PMRepair"] += self.env.now - t
                t = self.env.now

            # TRAVEL
            if DEBUG:
                print("Shovel%d     is traveling towards its site    at %.2f." %(self.id,self.env.now))
            self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     is traveling towards its site  at %.2f." %(self.id,self.env.now))
            yield self.env.process(self.travel(workshop.coordinates))
            if DEBUG:
                print("Shovel%d     arrived at its site        at %.2f." %(self.id,self.env.now))
            self.env.statistics["Shovel%d" %self.id]["History"].append("Shovel%d     arrived at its site            at %.2f." %(self.id,self.env.now))
            self.env.statistics["Shovel%d" %self.id]["Statistics"]["TravelTime"] += self.env.now - t
            t = self.env.now
        # REGENERATE THE FAULT EVENT
        self.failure = self.env.process(self.fault())


class DumpSite(Server):
    """
    The class inherits the basic attributes from :class:`Server` and replicates the behavior of a dumpsite.
    """

    def __init__(self, env, id, coordinates,mu,sigma):
        super().__init__(env, id, coordinates,mu,sigma)
        self.machine = simpy.Resource(env,capacity=1)
        env.statistics["DumpSite%d" %self.id] = list()

    def unload(self,truck,amount):
        self.env.statistics["DumpSite%d" %self.id].append([self.env.now, truck.capacity])
        yield self.env.timeout(self.servingTime())

    def waitingTime(self):
        return (len(self.machine.queue) + self.machine.count) * self.mu


class WorkShop(Server):
    """
    The class inherits the basic attributes from :class:`Server` and replicates the behavior of a workshop.
    The serving time depends on the repair time of the item under repair and on the type of maintenance, i.e., corrective or preventive.
    """

    def __init__(self, env, id, coordinates):
        super().__init__(env, id, coordinates)
        self.machine = simpy.PriorityResource(env,capacity=1)

    def correctiveRepair(self,equipment):
        ttr = equipment.timeToRepairCorrective()
        equipment.lastMaintenance = self.env.now + ttr
        yield self.env.timeout(ttr)

    def preventiveMaintenance(self,equipment):
        ttr = equipment.timeToRepairPreventive()
        equipment.lastMaintenance = self.env.now + ttr
        yield self.env.timeout(ttr)

    def waitingTime(self):
        return len(self.machine.queue) + self.machine.count


class MonitoredPriorityResource(simpy.PriorityResource):
    def __init__(self, *args, item_id=None, item_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = item_id
        self.item_type = item_type

    def request(self, *args, **kwargs):
        self._env.statistics[self.item_type + str(self.id) + "_queue"].append([self._env.now, len(self.queue)])
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        self._env.statistics[self.item_type + str(self.id) + "_queue"].append([self._env.now, len(self.queue)])
        return super().release(*args, **kwargs)


class MonitoredPreemptiveResource(simpy.PreemptiveResource):
    def __init__(self, *args, item_id=None, item_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = item_id
        self.item_type = item_type

    def request(self, *args, **kwargs):
        self._env.statistics[self.item_type + str(self.id) + "_queue"].append([self._env.now, len(self.queue)])
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        self._env.statistics[self.item_type + str(self.id) + "_queue"].append([self._env.now, len(self.queue)])
        return super().release(*args, **kwargs)
